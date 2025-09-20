from __future__ import annotations

import os
from typing import Callable, Iterator

from pytest import fixture
from wandb import Api
from wandb.apis.public import Registry, User

from tests.system_tests.backend_fixtures import random_string


@fixture(scope="module")
def user(module_mocker, backend_fixture_factory) -> Iterator[str]:
    """Module-scoped admin user overriding the default user fixture.

    We need admin privileges to look up users via the public API.
    """
    username = backend_fixture_factory.make_user(admin=True)

    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    module_mocker.patch.dict(os.environ, envvars)
    yield username


@fixture
def registry(make_registry, org: str, worker_id: str) -> Registry:
    """A registry for testing user/team member methods in this module."""
    return make_registry(
        organization=org,
        name=f"test-members-{random_string()}-{worker_id}",
        visibility="organization",
        description="Registry for user member tests",
    )


@fixture
def make_wandb_user(backend_fixture_factory, api: Api) -> Callable[[], User]:
    """A factory fixture that generates an actual `User` object."""

    def _make_wandb_user() -> User:
        username = backend_fixture_factory.make_user()
        wandb_user = api.user(username)
        assert wandb_user is not None
        return wandb_user

    return _make_wandb_user


def test_registry_add_user_members(registry: Registry, make_wandb_user):
    num_to_add = 3

    # Create a new non-admin user to add as a registry member
    members_to_add = [make_wandb_user() for _ in range(num_to_add)]
    expected_usernames = [user.username for user in members_to_add]

    # Add the user and verify they show up in user_members()
    registry.add_members(*members_to_add)

    actual_members = registry.user_members()
    assert all([isinstance(m.user, User) for m in actual_members])
    actual_usernames = {m.user.username for m in actual_members}
    assert set(expected_usernames).issubset(actual_usernames)


def test_registry_update_member_role(registry: Registry, make_wandb_user):
    num_to_add = 3

    # Create a new non-admin user to add as a registry member
    members = [make_wandb_user() for _ in range(num_to_add)]
    expected_usernames = [user.username for user in members]

    # Add the users, and update the last user's role to "admin"
    registry = registry.add_members(*members).update_member(members[-1], role="admin")

    # TODO: verify that the flag is reflected -- incorporate
    #   the registry-specific role into what's returned by
    #   registry.user_members()
    #   registry.team_members()
    #   ... since User.admin isn't registry-specific

    actual_members = registry.user_members()
    assert all([isinstance(m.user, User) for m in actual_members])
    actual_usernames = {m.user.username for m in actual_members}
    assert set(expected_usernames).issubset(actual_usernames)


def test_registry_user_members_add_and_remove(make_wandb_user, registry: Registry):
    # Create two users and add them via different accepted argument shapes
    user1 = make_wandb_user()
    user2 = make_wandb_user()

    # Add one via User object, one via ID
    registry.add_members(user1, user2.id)

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
