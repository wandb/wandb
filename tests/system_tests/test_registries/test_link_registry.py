from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import wandb
from pytest import FixtureRequest, fixture, skip
from typing_extensions import assert_never
from wandb import Api, Artifact
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.util import random_string

if TYPE_CHECKING:
    from ..backend_fixtures import BackendFixtureFactory, TeamAndOrgNames


@fixture
def team_and_org(
    backend_fixture_factory: BackendFixtureFactory, user: str
) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=user)


@fixture
def team(team_and_org: TeamAndOrgNames) -> str:
    return team_and_org.team


@fixture
def org(team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return team_and_org.org


@fixture
def org_entity(org: str, api: Api) -> str:
    if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
        skip("Cannot fetch org entity on this server version.")

    return fetch_org_entity_from_organization(api.client, org)


@fixture
def registry(org: str, api: Api, worker_id: str) -> Registry:
    # Full name will be "wandb-registry-model"
    if not InternalApi()._server_supports(
        ServerFeature.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION
    ):
        skip("Cannot create a test registry on this server version.")

    return api.create_registry(
        name="model", visibility="organization", organization=org
    )


@fixture
def source_artifact(team: str, worker_id: str) -> Artifact:
    # In order to link to an org registry, the source artifact must be logged
    # within a TEAM entity, NOT the user's personal entity.
    with wandb.init(entity=team) as run:
        artifact = Artifact(name="test-artifact", type="dataset")
        return run.log_artifact(artifact)


@fixture
def target_collection_name(worker_id: str) -> str:
    """The name of the target collection to link to."""
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
        "{org_entity}/{registry_name}/{collection_name}",
        "{registry_name}/{collection_name}",
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
        registry_name=registry.full_name,
        collection_name=target_collection_name,
    )


@fixture(params=["by_run", "by_artifact"])
def linked_artifact(
    request: FixtureRequest,
    target_path: str,
    source_artifact: Artifact,
    aliases: list[str] | None,
) -> Artifact:
    """A fixture that links the artifact to a registry collection.

    This is parameterized to test that the behavior of `Artifact.link()` and `Run.link_artifact()`
    are equivalent.
    """
    # Link to the target collection
    mode: Literal["by_run", "by_artifact"] = request.param
    if mode == "by_run":
        with wandb.init() as run:
            linked = run.link_artifact(source_artifact, target_path, aliases=aliases)

    elif mode == "by_artifact":
        linked = source_artifact.link(target_path, aliases=aliases)

    else:
        assert_never(mode)

    assert linked is not None  # precondition check
    return linked


def test_artifact_link_to_registry_collection(
    team: str,
    api: Api,
    org_entity: str,
    target_path: str,
    registry: Registry,
    source_artifact: Artifact,
    linked_artifact: Artifact,
    aliases: list[str] | None,
    target_collection_name: str,
    worker_id: str,
):
    linked = linked_artifact  # for brevity and convenience

    assert set(linked.aliases) == {"latest", *(aliases or [])}
    assert linked.collection.name == target_collection_name
    assert linked.collection.entity == org_entity
    assert linked.project == registry.full_name

    expected_linked_full_name = (
        f"{org_entity}/{registry.full_name}/{target_collection_name}:{linked.version}"
    )
    assert expected_linked_full_name == linked.qualified_name
