from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest import fixture, mark, raises
from wandb.errors import UnsupportedError
from wandb.sdk.artifacts._gqlutils import resolve_org_entity_name

if TYPE_CHECKING:
    from wandb import Api


@fixture
def mock_gql_response(wandb_backend_spy):
    """Factory fixture for setting up a mock GQL response."""

    def _stub_response(
        *,
        operation: str,
        variables: dict[str, Any],
        data: dict[str, Any],
    ) -> None:
        gql = wandb_backend_spy.gql
        wandb_backend_spy.stub_gql(
            gql.Matcher(operation=operation, variables=variables),
            gql.Constant(content={"data": data}),
        )

    return _stub_response


@fixture
def mock_org_entity_support(mock_gql_response):
    mock_gql_response(
        operation="TypeInfo",
        variables={"name": "Organization"},
        data={
            "__type": {
                "name": "Organization",
                "fields": [
                    {"name": "name", "args": []},
                    {"name": "orgEntity", "args": []},
                ],
                "inputFields": [],
            }
        },
    )


@fixture
def mock_no_org_entity_support(mock_gql_response):
    mock_gql_response(
        operation="TypeInfo",
        variables={"name": "Organization"},
        data={
            "__type": {
                "name": "Organization",
                "fields": [],
                "inputFields": [],
            }
        },
    )


@mark.parametrize(
    ["entity", "input_org", "expected_org_entity"],
    [
        ("entity", "org-display", "org-entity"),
        ("entity", "org-entity", "org-entity"),
        ("entity", None, "org-entity"),
    ],
)
@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_team_org_success(
    mock_gql_response,
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_team_org_invalid_org(mock_gql_response, api: Api):
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
@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_single_personal_org_success(
    mock_gql_response,
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_single_personal_org_invalid_org(
    mock_gql_response, api: Api
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_multiple_orgs_no_org_specified(
    mock_gql_response, api: Api
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_multiple_orgs_display_name(
    mock_gql_response, api: Api
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_multiple_orgs_entity_name(
    mock_gql_response, api: Api
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_multiple_orgs_invalid_org(
    mock_gql_response, api: Api
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


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_nonexistent_entity(mock_gql_response, api: Api):
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


@mark.usefixtures(mock_no_org_entity_support.__name__)
def test_resolve_org_entity_name_with_old_server(api: Api):
    entity = "any-entity"

    # Should error without organization
    with raises(UnsupportedError, match="unavailable for your server version"):
        resolve_org_entity_name(api.client, entity)

    # Should return organization as-is when specified
    assert (
        resolve_org_entity_name(api.client, entity, "org-name-input")
        == "org-name-input"
    )


@mark.usefixtures(mock_org_entity_support.__name__)
def test_resolve_org_entity_name_with_single_org_missing_entity_errors(
    mock_gql_response, api: Api
):
    entity = ""

    # Should error without organization if entity is missing/empty regardless of server capabilities
    with raises(
        ValueError, match="Entity name is required to resolve org entity name."
    ):
        resolve_org_entity_name(api.client, entity)
