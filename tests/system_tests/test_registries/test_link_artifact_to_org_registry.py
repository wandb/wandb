from __future__ import annotations

import os
from typing import TYPE_CHECKING

import wandb
from pytest import FixtureRequest, fixture
from pytest_mock import MockerFixture
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.sdk.artifacts.artifact import Artifact
from wandb.util import random_string

if TYPE_CHECKING:
    from ..backend_fixtures import BackendFixtureFactory, TeamAndOrgNames


@fixture(scope="session")
def user(
    session_mocker: MockerFixture,
    backend_fixture_factory: BackendFixtureFactory,
) -> str:
    username = backend_fixture_factory.make_user()
    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    session_mocker.patch.dict(os.environ, envvars)
    return username


@fixture(scope="session")
def team_and_org(
    backend_fixture_factory: BackendFixtureFactory, user: str
) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=user)


@fixture(scope="session")
def team(team_and_org: TeamAndOrgNames) -> str:
    return team_and_org.team


@fixture(scope="session")
def org(team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return team_and_org.org


@fixture(scope="session")
def api(user, org) -> wandb.Api:
    return wandb.Api()


@fixture(scope="session")
def org_entity(api: wandb.Api, org: str) -> str:
    return fetch_org_entity_from_organization(api.client, org)


@fixture(scope="session")
def registry(api: wandb.Api, org: str) -> Registry:
    # Full name will be "wandb-registry-model"
    return api.create_registry("model", visibility="organization", organization=org)


@fixture(scope="session")
def source_artifact(team: str) -> Artifact:
    """Create a source artifact logged within a team entity.

    Log this once per session to reduce overhead for each test run.
    This should be fine as long as we're mainly testing linking functionality.
    """
    # In order to link to an org registry, the source artifact must be logged
    # within a team entity, NOT the user's personal entity.
    with wandb.init(entity=team) as run:
        artifact = wandb.Artifact(name="test-artifact", type="dataset")
        return run.log_artifact(artifact).wait()


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


def test_artifact_link_vs_run_link_artifact_on_registry_collection(
    user: str,
    aliases: list[str] | None,
    team: str,
    org: str,
    org_entity: str,
    registry: Registry,
    source_artifact: Artifact,
    target_collection_name: str,
):
    # Link to a new collection for each test run
    with wandb.init(entity=team) as run:
        target_path = f"{org_entity}/{registry.full_name}/{target_collection_name}"

        linked_by_run = run.link_artifact(source_artifact, target_path, aliases=aliases)
        linked_by_artifact = source_artifact.link(target_path, aliases=aliases)

    for linked_art in (linked_by_run, linked_by_artifact):
        assert linked_art is not None

        assert set(linked_art.aliases) == {"latest", *(aliases or [])}
        assert linked_art.collection.name == target_collection_name
        assert linked_art.collection.entity == org_entity
        assert linked_art.project == registry.full_name
        assert linked_art.qualified_name == f"{target_path}:{linked_art.version}"
