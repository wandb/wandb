from __future__ import annotations

import os
from typing import TYPE_CHECKING

import wandb
from pytest import fixture, mark
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
def team_and_org(backend_fixture_factory, user) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=user)


@fixture(scope="session")
def team(team_and_org: TeamAndOrgNames) -> str:
    return team_and_org.team


@fixture(scope="session")
def organization(team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return team_and_org.org


@fixture(scope="session")
def api(user, organization) -> wandb.Api:
    return wandb.Api()


@fixture(scope="session")
def org_entity(organization, api: wandb.Api) -> str:
    return fetch_org_entity_from_organization(api.client, organization)


@fixture(scope="session")
def registry(organization, user, api: wandb.Api) -> Registry:
    return api.create_registry(
        name="potatoes",
        visibility="organization",
        organization=organization,
    )


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
        return run.log_artifact(artifact)


@mark.parametrize(
    "aliases",
    (
        ["alias1", "alias2"],
        ["alias1"],
        [],
        None,
    ),
)
def test_artifact_link_to_registry_collection(
    worker_id: str,
    api: wandb.Api,
    aliases: list[str] | None,
    team: str,
    organization: str,
    org_entity: str,
    registry: Registry,
    source_artifact: Artifact,
):
    with wandb.init(entity=team) as run:
        # Link to a new collection for each test run
        target_collection = f"collection-{worker_id}-{random_string(8)}"

        target_path = f"{org_entity}/{registry.full_name}/{target_collection}"

        linked_by_run = run.link_artifact(
            artifact=source_artifact,
            target_path=target_path,
            aliases=aliases,
        )

        linked_by_artifact = source_artifact.link(
            target_path=target_path,
            aliases=aliases,
        )

    for linked_art in (linked_by_run, linked_by_artifact):
        assert linked_art is not None

        assert set(linked_art.aliases) == {"latest", *(aliases or [])}
        assert linked_art.collection.name == target_collection
        assert linked_art.collection.entity == org_entity
        assert linked_art.project == registry.full_name
        assert linked_art.qualified_name == f"{target_path}:{linked_art.version}"
