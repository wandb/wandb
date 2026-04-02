from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pytest import fixture, mark, raises
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._gqlutils import resolve_org_entity_name, server_supports

if TYPE_CHECKING:
    from wandb import Api

    from tests.fixtures.wandb_backend_spy import WandbBackendSpy

    class GQLResponseMocker(Protocol):
        def __call__(
            self,
            *,
            operation: str,
            variables: dict[str, Any],
            data: dict[str, Any],
        ) -> None: ...


@fixture
def mock_gql_response(wandb_backend_spy: WandbBackendSpy) -> GQLResponseMocker:
    """Factory fixture for setting up a mock GQL response."""
    from tests.fixtures.wandb_backend_spy.gql_match import Constant, Matcher

    def stub_response(
        *,
        operation: str,
        variables: dict[str, Any],
        data: dict[str, Any],
    ) -> None:
        wandb_backend_spy.stub_gql(
            Matcher(operation=operation, variables=variables),
            Constant(content={"data": data}),
        )

    return stub_response


@mark.parametrize(
    ["entity", "input_org", "expected_org_entity"],
    [
        ("entity", "org-display", "org-entity"),
        ("entity", "org-entity", "org-entity"),
        ("entity", None, "org-entity"),
    ],
)
def test_resolve_org_entity_name_with_team_org_success(
    mock_gql_response: GQLResponseMocker,
    api: Api,
    entity,
    input_org,
    expected_org_entity,
):
    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": {
                    "name": "org-display",
                    "orgEntity": {"name": "org-entity"},
                },
                "user": None,
            }
        },
    )

    assert resolve_org_entity_name(api.client, entity, input_org) == expected_org_entity


def test_resolve_org_entity_name_with_team_org_invalid_org(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": {
                    "name": "org-display",
                    "orgEntity": {"name": "org-entity"},
                },
                "user": None,
            }
        },
    )

    with raises(ValueError, match="Unable to find organization for entity"):
        resolve_org_entity_name(api.client, entity, "potato-org")


@mark.parametrize(
    ["entity", "input_org", "expected_org_entity"],
    [
        ("entity", "org-display", "org-entity"),
        ("entity", "org-entity", "org-entity"),
        ("entity", None, "org-entity"),
    ],
)
def test_resolve_org_entity_name_with_single_personal_org_success(
    mock_gql_response: GQLResponseMocker,
    api: Api,
    entity,
    input_org,
    expected_org_entity,
):
    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org-display", "orgEntity": {"name": "org-entity"}},
                    ],
                },
            }
        },
    )

    assert resolve_org_entity_name(api.client, entity, input_org) == expected_org_entity


def test_resolve_org_entity_name_with_single_personal_org_invalid_org(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org-display", "orgEntity": {"name": "org-entity"}},
                    ],
                },
            }
        },
    )

    with raises(
        ValueError, match="Expecting the organization name or entity name to match"
    ):
        resolve_org_entity_name(api.client, entity, "potato-org")


def test_resolve_org_entity_name_with_multiple_orgs_no_org_specified(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org1-display", "orgEntity": {"name": "org1-entity"}},
                        {"name": "org2-display", "orgEntity": {"name": "org2-entity"}},
                        {"name": "org3-display", "orgEntity": {"name": "org3-entity"}},
                    ],
                },
            }
        },
    )

    with raises(ValueError, match="belongs to multiple organizations"):
        resolve_org_entity_name(api.client, entity)


def test_resolve_org_entity_name_with_multiple_orgs_display_name(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org1-display", "orgEntity": {"name": "org1-entity"}},
                        {"name": "org2-display", "orgEntity": {"name": "org2-entity"}},
                    ],
                },
            }
        },
    )

    assert resolve_org_entity_name(api.client, entity, "org1-display") == "org1-entity"


def test_resolve_org_entity_name_with_multiple_orgs_entity_name(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org1-display", "orgEntity": {"name": "org1-entity"}},
                        {"name": "org2-display", "orgEntity": {"name": "org2-entity"}},
                    ],
                },
            }
        },
    )

    assert resolve_org_entity_name(api.client, entity, "org2-entity") == "org2-entity"


def test_resolve_org_entity_name_with_multiple_orgs_invalid_org(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": {
                    "organizations": [
                        {"name": "org1-display", "orgEntity": {"name": "org1-entity"}},
                        {"name": "org2-display", "orgEntity": {"name": "org2-entity"}},
                    ],
                },
            }
        },
    )
    with raises(ValueError, match="Personal entity belongs to multiple organizations"):
        resolve_org_entity_name(api.client, entity, "potato-org")


def test_resolve_org_entity_name_with_nonexistent_entity(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = "missing-entity"

    mock_gql_response(
        operation="FetchOrgInfoFromEntity",
        variables={"entity": entity},
        data={
            "entity": {
                "organization": None,
                "user": None,
            }
        },
    )

    with raises(ValueError, match="Unable to find organization for entity"):
        resolve_org_entity_name(api.client, entity)


def test_resolve_org_entity_name_with_single_org_missing_entity_errors(
    mock_gql_response: GQLResponseMocker, api: Api
):
    entity = ""

    # Should error without organization if entity is missing/empty regardless of server capabilities
    with raises(
        ValueError, match="Entity name is required to resolve org entity name."
    ):
        resolve_org_entity_name(api.client, entity)


def test_server_supports__known_feature(
    mock_gql_response: GQLResponseMocker,
    api: Api,
):
    mock_gql_response(
        operation="ServerFeaturesQuery",
        variables={},
        data={
            "serverInfo": {
                "features": [
                    {"name": "LARGE_FILENAMES", "isEnabled": True},
                ],
            },
        },
    )

    assert server_supports(api.client, pb.ServerFeature.LARGE_FILENAMES)


def test_server_supports__unknown_feature(
    mock_gql_response: GQLResponseMocker,
    api: Api,
):
    mock_gql_response(
        operation="ServerFeaturesQuery",
        variables={},
        data={
            "serverInfo": {
                "features": [
                    {"name": "LARGE_FILENAMES", "isEnabled": True},
                ],
            },
        },
    )

    assert not server_supports(api.client, "NOT_A_REAL_FEATURE")
    assert not server_supports(api.client, 9999)
