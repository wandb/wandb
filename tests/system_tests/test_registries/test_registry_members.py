from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, Iterator

from pytest import fixture, mark
from wandb import Api
from wandb.apis.public import Registry, Team, User
from wandb.apis.public.registries._members import MemberKind

if TYPE_CHECKING:
    from tests.system_tests.backend_fixtures import BackendFixtureFactory


@fixture(scope="module")
def user(
    module_mocker, backend_fixture_factory: BackendFixtureFactory
) -> Iterator[str]:
    """Module-scoped admin user that deliberately overrides the default user fixture.

    We need admin privileges to perform some of the setup steps via the public API.
    """
    username = backend_fixture_factory.make_user(admin=True)

    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    module_mocker.patch.dict(os.environ, envvars)
    yield username


@fixture(scope="module")
def admin_user(user: str) -> User:
    """Module-scoped fixture that returns an actual `User` object for the admin user."""
    return Api().user(user)


@fixture
def registry(
    make_registry: Callable[..., Registry], org: str, worker_id: str
) -> Registry:
    """A registry for testing user/team member methods in this module."""
    from tests.system_tests.backend_fixtures import random_string

    return make_registry(
        organization=org,
        name=f"test-members-{random_string()}-{worker_id}",
        visibility="organization",
        description="Registry for user member tests",
    )


@fixture
def make_wandb_users(
    backend_fixture_factory: BackendFixtureFactory, api: Api
) -> Callable[[int], list[User]]:
    """A factory fixture that generates multiple actual `User` objects."""

    def _make_wandb_users(count: int) -> list[User]:
        names = [backend_fixture_factory.make_user() for _ in range(count)]
        objs = [api.user(name) for name in names]
        assert None not in objs
        return objs

    return _make_wandb_users


@fixture
def make_wandb_teams(
    backend_fixture_factory: BackendFixtureFactory, user: str, api: Api, worker_id: str
) -> Callable[[int], list[Team]]:
    """A factory fixture that generates multiple actual `Team` objects."""
    from tests.system_tests.backend_fixtures import random_string

    def _make_wandb_teams(count: int) -> list[Team]:
        names = [f"test-team-{random_string()}-{worker_id}" for _ in range(count)]
        return [api.create_team(name, admin_username=user) for name in names]

    return _make_wandb_teams


def test_registry_add_user_members(
    admin_user: User, registry: Registry, make_wandb_users
):
    """Check that user members can be programmatically added to a registry."""
    # Create users to add as registry members, and other users that aren't added
    added_users = make_wandb_users(3)
    other_users = make_wandb_users(2)

    # Add the user and verify they show up in user_members()
    registry.add_members(*added_users)

    actual_members = registry.user_members()
    actual_member_users = [m.user for m in actual_members]

    # Since the allowed `User` attributes aren't well-constrained for now,
    # equality checks on `User` objects are brittle.  Check usernames/ids instead.
    expected_users = {admin_user, *added_users}

    actual_user_names = {u.username for u in actual_member_users}
    actual_user_ids = {u.id for u in actual_member_users}

    assert {u.username for u in expected_users} == actual_user_names
    assert {u.id for u in expected_users} == actual_user_ids
    assert len(expected_users) == len(actual_members)

    # Check that the other users are definitely not members
    assert {u.username for u in other_users}.isdisjoint(actual_user_names)
    assert {u.id for u in other_users}.isdisjoint(actual_user_ids)


def test_registry_add_team_members(registry: Registry, make_wandb_teams):
    """Check that team members can be programmatically added to a registry."""
    # Create teams to add as registry members, and other teams that aren't added
    added_teams = make_wandb_teams(3)
    other_teams = make_wandb_teams(2)

    # Add the team and verify they show up in team_members()
    registry.add_members(*added_teams)

    actual_members = registry.team_members()
    actual_member_teams = [m.team for m in actual_members]

    # Since the allowed `Team` attributes aren't well-constrained for now,
    # equality checks on `Team` objects are brittle.  Check names/ids instead.
    expected_teams = added_teams

    actual_team_names = {t.name for t in actual_member_teams}
    actual_team_ids = {t.id for t in actual_member_teams}

    assert {t.name for t in expected_teams} == actual_team_names
    assert {t.id for t in expected_teams} == actual_team_ids
    assert len(expected_teams) == len(actual_members)

    # Check that the other teams are definitely not members
    assert {t.name for t in other_teams}.isdisjoint(actual_team_names)
    assert {t.id for t in other_teams}.isdisjoint(actual_team_ids)


def test_registry_add_members_with_mixed_args(
    admin_user: User, registry: Registry, make_wandb_users, make_wandb_teams
):
    """Check that mixed user and team members can be added to a registry, and by object or ID."""
    # Create both users and teams to add as registry members
    added_teams = make_wandb_teams(3)
    added_users = make_wandb_users(3)

    team1, team2, team3 = added_teams
    user1, user2, user3 = added_users

    # Add the teams and users and verify they show up in members()
    # Mix up the order of the arguments, as well as whether they're passed as objects or IDs
    added = [team1, user1, team2.id, user2, team3, user3.id]
    registry.add_members(*added)

    expected_member_teams = added_teams
    expected_member_users = [admin_user, *added_users]

    actual_members = registry.members()
    actual_member_teams = [m.team for m in actual_members if m.kind is MemberKind.TEAM]
    actual_member_users = [m.user for m in actual_members if m.kind is MemberKind.USER]

    actual_team_names = {t.name for t in actual_member_teams}
    actual_team_ids = {t.id for t in actual_member_teams}

    actual_user_names = {u.username for u in actual_member_users}
    actual_user_ids = {u.id for u in actual_member_users}

    assert {t.name for t in expected_member_teams} == actual_team_names
    assert {t.id for t in expected_member_teams} == actual_team_ids

    assert {u.username for u in expected_member_users} == actual_user_names
    assert {u.id for u in expected_member_users} == actual_user_ids

    expected_member_count = len(expected_member_teams) + len(expected_member_users)
    assert expected_member_count == len(actual_members)


@mark.parametrize("target_role", ["admin", "member", "viewer", "restricted_viewer"])
def test_registry_update_user_member_role(
    admin_user: User, registry: Registry, make_wandb_users, target_role: str
):
    """Check that user member roles can be updated."""
    # Create new non-admin users to add as registry members
    users = make_wandb_users(3)

    # Add the users.  Update the last user's role to be any supported target role.
    target_user = users[-1]
    registry = registry.add_members(*users).update_member(target_user, role=target_role)
    actual_members = registry.user_members()

    # Consistency checks
    actual_user_ids = {m.user.id for m in actual_members}
    actual_user_names = {m.user.username for m in actual_members}
    assert target_user.id in actual_user_ids
    assert target_user.username in actual_user_names
    assert admin_user.id in actual_user_ids
    assert admin_user.username in actual_user_names

    for member in actual_members:
        if member.user.username == target_user.username:
            assert member.role == target_role
            assert member.user.id == target_user.id
            assert member.user.email == target_user.email

        if member.user.username == admin_user.username:
            assert member.role == "admin"
            assert member.user.id == admin_user.id
            assert member.user.email == admin_user.email


@mark.parametrize("target_role", ["admin", "member", "viewer", "restricted_viewer"])
def test_registry_update_team_member_role(
    registry: Registry, make_wandb_teams, target_role: str
):
    """Check that team member roles can be updated."""
    # Create teams to add as registry members
    teams = make_wandb_teams(3)

    # Add the teams.  Update the last team's role to be any supported target role.
    target_team = teams[-1]
    registry = registry.add_members(*teams).update_member(target_team, role=target_role)
    actual_members = registry.team_members()

    # Consistency checks
    actual_team_ids = {m.team.id for m in actual_members}
    actual_team_names = {m.team.name for m in actual_members}
    assert target_team.id in actual_team_ids
    assert target_team.name in actual_team_names

    for member in registry.team_members():
        if member.team.name == target_team.name:
            assert member.role == target_role
            assert member.team.id == target_team.id


def test_registry_user_members_add_and_remove(make_wandb_users, registry: Registry):
    """Check that sequential add and remove operations work as expected."""
    # Create two users and add them via different accepted argument shapes
    user1, user2 = make_wandb_users(2)

    # Add one via User object, one via ID
    registry.add_members(user1, user2)

    members_after_add = registry.user_members()
    usernames_after_add = {u.user.username for u in members_after_add}
    assert {user1.username, user2.username}.issubset(usernames_after_add)

    # Remove one user and verify they no longer appear
    registry.remove_members(user1)

    members_after_remove1 = registry.user_members()
    usernames_after_remove1 = {u.user.username for u in members_after_remove1}
    assert user1.username not in usernames_after_remove1
    assert user2.username in usernames_after_remove1

    # Remove the other user by ID
    registry.remove_members(user2.id)

    # Check that neither user is a member anymore
    members_after_remove2 = registry.user_members()
    usernames_after_remove2 = {u.user.username for u in members_after_remove2}
    assert user1.username not in usernames_after_remove2
    assert user2.username not in usernames_after_remove2

    # Removing the 2nd user again shouldn't do anything, but shouldn't error (idempotence)
    registry.remove_members(user2)
    members_after_remove3 = registry.user_members()
    usernames_after_remove3 = {u.user.username for u in members_after_remove3}
    assert user1.username not in usernames_after_remove3
    assert user2.username not in usernames_after_remove3
