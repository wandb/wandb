from __future__ import annotations

import os
from typing import TYPE_CHECKING

import wandb
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.util import random_string

if TYPE_CHECKING:
    from ..backend_fixtures import BackendFixtureFactory, TeamAndOrgNames


@fixture(scope="module")
def user(backend_fixture_factory: BackendFixtureFactory) -> str:
    return backend_fixture_factory.make_user(admin=True)


@fixture(scope="module")
def team_and_org(
    user: str, backend_fixture_factory: BackendFixtureFactory
) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=user)


@fixture(scope="module")
def team(team_and_org: TeamAndOrgNames) -> str:
    return team_and_org.team


@fixture(scope="module")
def org(team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return team_and_org.org


@fixture(scope="module")
def api(module_mocker: MockerFixture, user: str, team: str, org: str) -> wandb.Api:
    envvars = {
        "WANDB_USERNAME": user,
        "WANDB_API_KEY": user,
        "WANDB_ENTITY": team,
    }
    module_mocker.patch.dict(os.environ, envvars)
    return wandb.Api()


@fixture(scope="module")
def org_entity(api: wandb.Api, org: str) -> str:
    if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
        skip("Cannot fetch org entity on this server version.")
    return fetch_org_entity_from_organization(api.client, org)


@fixture(scope="module")
def registry(api: wandb.Api, org: str, worker_id: str) -> Registry:
    # Full name will be "wandb-registry-model"
    return api.create_registry(
        f"model-{worker_id}-{random_string(8)}",
        visibility="organization",
        organization=org,
    )


@fixture(scope="module")
def source_artifact(team: str, worker_id: str) -> Artifact:
    """Create a source artifact logged within a team entity.

    Log this once per module to reduce overhead for each test run.
    This should be fine as long as we're mainly testing linking functionality.
    """
    # In order to link to an org registry, the source artifact must be logged
    # within a team entity, NOT the user's personal entity.
    artifact = wandb.Artifact(
        name=f"test-artifact-{worker_id}-{random_string(8)}", type="dataset"
    )
    with wandb.init(entity=team) as run:
        logged = run.log_artifact(artifact)
        logged.wait()
        return logged


@fixture
def target_collection_name(worker_id: str) -> str:
    return f"collection-{worker_id}-{random_string(8)}"


@fixture(
    params=[
        ["alias1", "alias2"],
        ["alias1"],
        [],
        None,
    ]
)
def aliases(request: FixtureRequest) -> list[str] | None:
    """Test aliases to apply when linking an artifact."""
    return request.param


@fixture(
    params=[
        "{org_entity}/{registry.full_name}/{target_collection_name}",
        "{registry.full_name}/{target_collection_name}",
    ]
)
def target_path(
    request: FixtureRequest,
    org_entity: str,
    registry: Registry,
    target_collection_name: str,
) -> str:
    """Test target path to link to.

    Parameterized over equivalent valid representations of the same target.
    """
    # Link to a new collection for each test run
    path_template = request.param
    return path_template.format(
        org_entity=org_entity,
        registry=registry,
        target_collection_name=target_collection_name,
    )


def test_artifact_link_vs_run_link_artifact_on_registry_collection(
    api: wandb.Api,
    org_entity: str,
    target_path: str,
    registry: Registry,
    source_artifact: Artifact,
    aliases: list[str] | None,
    target_collection_name: str,
):
    linked = source_artifact.link(target_path, aliases=aliases)

    assert linked is not None

    assert set(linked.aliases) == {"latest", *(aliases or [])}
    assert linked.collection.name == target_collection_name
    assert linked.collection.entity == org_entity
    assert linked.project == registry.full_name

    expected_linked_full_name = (
        f"{org_entity}/{registry.full_name}/{target_collection_name}:{linked.version}"
    )
    assert expected_linked_full_name == linked.qualified_name
