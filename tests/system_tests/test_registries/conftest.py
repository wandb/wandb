from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable

import wandb
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb import Api, Artifact
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.util import random_string
from wandb_gql import gql

if TYPE_CHECKING:
    from ..backend_fixtures import BackendFixtureFactory, TeamAndOrgNames


@fixture
def skip_if_server_does_not_support_create_registry(user_in_orgs_factory, api) -> None:
    """Skips the test for older server versions that do not support Api.create_registry()."""
    if not server_supports(api.client, pb.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION):
        skip("Cannot create a test registry on this server version.")


@fixture
def make_registry(
    skip_if_server_does_not_support_create_registry: None,
    api: Api,
) -> Callable[..., Registry]:
    """A factory fixture that creates test registries directly via Api.create_registry().

    Requesting this fixture will automatically skip the test if the server does not
    support creating registries.
    """
    return api.create_registry


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
    if not server_supports(api.client, pb.ARTIFACT_REGISTRY_SEARCH):
        skip("Cannot fetch org entity on this server version.")

    return fetch_org_entity_from_organization(api.client, org)


@fixture
def registry(
    org: str,
    make_registry,
    worker_id: str,
) -> Registry:
    return make_registry(name="model", visibility="organization", organization=org)


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


@fixture
def other_team_and_org(
    backend_fixture_factory: BackendFixtureFactory, user: str
) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=user)


@fixture
def other_team(other_team_and_org: TeamAndOrgNames) -> str:
    return other_team_and_org.team


@fixture
def other_org(other_team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return other_team_and_org.org


@fixture(params=[team.__name__, other_team.__name__])
def set_team_as_default_entity(request: FixtureRequest, mocker: MockerFixture) -> None:
    """Sets the server-side defaultEntity and the local WANDB_ENTITY envvar for the test run."""
    team_entity: str = request.getfixturevalue(request.param)

    # Eh, this will have to do for now.
    # Set the server-side default entity for the user for the test run.
    wandb.Api().client.execute(
        gql(
            """
            mutation SetDefaultEntity($entity: String!) {
                updateUser(input: {defaultEntity: $entity}) {
                    user { id }
                }
            }
            """
        ),
        variable_values={"entity": team_entity},
    )
    # Set the local WANDB_ENTITY environment variable as well.
    mocker.patch.dict(os.environ, {**os.environ, "WANDB_ENTITY": team_entity})

    # consistency check
    test_api = wandb.Api()
    assert test_api.default_entity == team_entity
    assert test_api.settings["entity"] == team_entity
