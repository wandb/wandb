"""System tests for `Api.organization()` and the public `Organization` model."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pytest import fixture, raises
from wandb import CommError

if TYPE_CHECKING:
    from wandb import Api


@fixture
def org_name(user_in_orgs_factory: Callable[..., object]) -> str:
    """The name of a single organization the test user belongs to."""
    user_org = user_in_orgs_factory(number_of_orgs=1)
    return user_org.organization_names[0]


def test_organization_by_name(api: Api, org_name: str):
    """`Api.organization(name)` fetches the org and its entity from a live server."""
    org = api.organization()
    named_org = api.organization(org_name)

    assert org == named_org

    # Extra consistency checks
    assert org.name == org_name
    assert named_org.name == org_name

    assert org.org_entity.entity_type == "organization"
    assert named_org.org_entity.entity_type == "organization"


def test_organization_not_found_raises(api: Api):
    """Looking up a nonexistent organization raises a clear error.

    The server resolves an unknown (or unreadable) org name to a null
    `organization`, which `Api.organization()` surfaces as a `ValueError`.
    """
    with raises(CommError, match="not found"):
        api.organization("this-org-does-not-exist-xyz")
