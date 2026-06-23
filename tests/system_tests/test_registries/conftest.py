from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

import wandb
from pytest import FixtureRequest, fixture, skip
from pytest_mock import MockerFixture
from wandb import Api, Artifact
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.apis.public.users import User
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.util import random_string

if TYPE_CHECKING:
    from ..backend_fixtures import BackendFixtureFactory, TeamAndOrgNames


@fixture
def skip_if_server_does_not_support_create_registry(user_in_orgs_factory, api) -> None:
    """Skips the test for older server versions that do not support Api.create_registry()."""
    if not server_supports(
        api._service_api,
        pb.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION,
    ):
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
    if not server_supports(api._service_api, pb.ARTIFACT_REGISTRY_SEARCH):
        skip("Cannot fetch org entity on this server version.")

    return fetch_org_entity_from_organization(api._service_api, org)


@fixture
def registry(
    org: str,
    make_registry,
    worker_id: str,
) -> Registry:
    return make_registry(name="model", visibility="organization", organization=org)


def _remove_from_team(api: Api, team: str, username: str) -> None:
    team_obj = api.team(team)
    team_obj.load(force=True)
    for member in team_obj.members:
        if member.username == username:
            member.delete()
            return


@fixture
def add_org_user_with_registry_access(
    request: FixtureRequest,
    backend_fixture_factory: BackendFixtureFactory,
    api: Api,
) -> Callable[..., tuple[str, User]]:
    """Create an org user with registry membership and optional source-team access.

    Uses the public API for steps that the fixture service does not support
    (registry project_members, team invites). Registers per-test finalizers to
    remove those rows before session teardown deletes the user.
    """

    def _add(
        *,
        org: str,
        org_role: Literal["admin", "member", "viewer"],
        registry: Registry,
        team: str,
        invite_to_source_team: bool,
        registry_role: Literal[
            "admin", "member", "viewer", "restricted_viewer"
        ] = "member",
    ) -> tuple[str, User]:
        username = backend_fixture_factory.add_org_user(org, role=org_role)
        user = api.user(username)
        assert user is not None

        registry.add_members(user).update_member(user, role=registry_role)
        request.addfinalizer(lambda: registry.remove_members(user))

        if invite_to_source_team:
            assert api.team(team).invite(username)
            request.addfinalizer(
                lambda: _remove_from_team(api, team, username),
            )

        return username, user

    return _add


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
    wandb.Api()._service_api.execute_graphql(
        (
            """
            mutation SetDefaultEntity($entity: String!) {
                updateUser(input: {defaultEntity: $entity}) {
                    user { id }
                }
            }
            """
        ),
        variables={"entity": team_entity},
    )
    # Set the local WANDB_ENTITY environment variable as well.
    mocker.patch.dict(os.environ, {**os.environ, "WANDB_ENTITY": team_entity})

    # consistency check
    test_api = wandb.Api()
    assert test_api.default_entity == team_entity
    assert test_api.settings["entity"] == team_entity
