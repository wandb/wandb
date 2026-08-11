from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pytest import fixture, mark, param, raises
from wandb.apis.public.registries import _utils
from wandb.apis.public.registries._utils import (
    advanced_search_enabled,
    prepare_artifact_types_input,
    prepare_registry_filter,
)
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)
from wandb.sdk.artifacts._generated import FetchAdvancedRegistryFeatures
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture
    from wandb.apis.paginator import RelayPaginator


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    mock = mocker.Mock(spec=ServiceApi)
    mock.feature_enabled.return_value = False
    return mock


@fixture
def enable_advanced_search(service_api: MagicMock) -> None:
    service_api.feature_enabled.return_value = True
    service_api.execute_graphql.return_value = (
        FetchAdvancedRegistryFeatures.model_validate(
            {"organization": {"advancedRegistryFeatures": {"advancedSearch": True}}}
        )
    )


@mark.parametrize(
    ("artifact_types", "expected_output"),
    [
        # Valid case
        (["my-valid-type_123"], [{"name": "my-valid-type_123"}]),
        (
            ["apple", "banana", "cherry"],
            [{"name": "apple"}, {"name": "banana"}, {"name": "cherry"}],
        ),
        # None/empty input
        (None, None),
        ([], None),
    ],
)
def test_format_gql_artifact_types_input_valid(artifact_types, expected_output):
    """Test artifact type name validation and formatting for valid inputs."""
    result = prepare_artifact_types_input(artifact_types=artifact_types)
    assert result == expected_output


@mark.parametrize(
    "artifact_types",
    [
        # Invalid characters
        (["valid_type", "invalid:::"]),
        (["invalid/type"]),
        (["invalid:type"]),
        # Too long
        (["a" * 129]),
    ],
)
def test_format_gql_artifact_types_input_error(artifact_types):
    """Test artifact type name validation raises errors for invalid inputs."""
    with raises(ValueError):
        prepare_artifact_types_input(artifact_types=artifact_types)


@mark.parametrize(
    ("raw", "expected"),
    [
        param(
            {"name": "model"},
            {"name": f"{REGISTRY_PREFIX}model"},
            id="bare-name-is-prefixed",
        ),
        param(
            {"name": f"{REGISTRY_PREFIX}model"},
            {"name": f"{REGISTRY_PREFIX}model"},
            id="prefixed-name-is-unchanged",
        ),
        param(
            {"$or": [{"name": "model1"}, {"tag": "prod"}]},
            {"$or": [{"name": f"{REGISTRY_PREFIX}model1"}, {"tag": "prod"}]},
            id="nested-list",
        ),
        param(
            {"name": {"$regex": "model.*"}},
            {"name": {"$regex": "model.*"}},
            id="regex-operand-is-unchanged",
        ),
        param(
            {"$unknownOp": {"name": "opaque"}, "name": "visible"},
            {
                "$unknownOp": {"name": "opaque"},
                "name": f"{REGISTRY_PREFIX}visible",
            },
            id="unknown-operator-operand-is-unchanged",
        ),
        param(
            {"name": {"$unknownOp": {"name": "opaque"}}},
            {"name": {"$unknownOp": {"name": "opaque"}}},
            id="unknown-name-operator-operand-is-unchanged",
        ),
        param(
            {"metadata": {"name": "not-a-registry-name"}},
            {"metadata": {"name": "not-a-registry-name"}},
            id="nested-name-in-another-field-is-unchanged",
        ),
        param(
            {"id": 1, "name": "model", "description": None},
            {"id": 1, "name": f"{REGISTRY_PREFIX}model", "description": None},
            id="mixed-fields-and-types",
        ),
        param(
            {
                "name": {
                    "$in": [
                        "project1",
                        f"{REGISTRY_PREFIX}project2",
                    ],
                    "$or": [
                        {"$regex": "project3"},
                        {"$eq": "project4"},
                        {"$eq": f"{REGISTRY_PREFIX}project5"},
                    ],
                }
            },
            {
                "name": {
                    "$in": [
                        f"{REGISTRY_PREFIX}project1",
                        f"{REGISTRY_PREFIX}project2",
                    ],
                    "$or": [
                        {"$regex": "project3"},
                        {"$eq": f"{REGISTRY_PREFIX}project4"},
                        {"$eq": f"{REGISTRY_PREFIX}project5"},
                    ],
                }
            },
            id="nested-dict",
        ),
        param(
            {"name": {"one": {"two": [{"three": "model"}]}}},
            {"name": {"one": {"two": [{"three": f"{REGISTRY_PREFIX}model"}]}}},
            id="deeply-nested-name-operand",
        ),
        # Non-dict and empty inputs are returned unchanged.
        param("string", "string", id="non-dict-string"),
        param({}, {}, id="empty-dict"),
        param(123, 123, id="non-dict-int"),
        param(None, None, id="None"),
        param(True, True, id="non-dict-bool"),
    ],
)
def test_prepare_registry_filter(raw, expected):
    assert prepare_registry_filter(raw) == expected


def test_basic_paginators_normalize_filters_without_feature_lookup(
    service_api: MagicMock,
):
    registries = Registries(
        service_api,
        organization="org",
        filter={"name": "model", "id": 1},
    )
    collections = Collections(
        service_api,
        organization="org",
        registry_filter={"name": "model"},
        collection_filter={"collection_id": 2, "tags": "prod"},
    )

    expected_registries_filters = {
        "filters": {"name": f"{REGISTRY_PREFIX}model", "id": 1},
    }
    expected_collections_filters = {
        "registryFilter": {"name": f"{REGISTRY_PREFIX}model"},
        "collectionFilter": {"artifact_collection_id": 2, "tag": "prod"},
    }

    assert (
        json.loads(registries.variables["filters"])
        == expected_registries_filters["filters"]
    )
    assert (
        json.loads(collections.variables["registryFilter"])
        == expected_collections_filters["registryFilter"]
    )
    assert (
        json.loads(collections.variables["collectionFilter"])
        == expected_collections_filters["collectionFilter"]
    )
    service_api.feature_enabled.assert_not_called()
    service_api.execute_graphql.assert_not_called()


def test_versions_uses_basic_filter_fields(service_api: MagicMock):
    versions = Versions(
        service_api,
        organization="org",
        registry_filter={"name": "model", "id": 1},
        collection_filter={"collection_id": 2, "tags": "prod"},
        artifact_filter={
            "artifact_metadata.owner": "alice",
            "version_index": 3,
        },
    )

    gql_vars = versions.variables

    expected_registry_filter = {"name": f"{REGISTRY_PREFIX}model", "id": 1}
    expected_collection_filter = {"artifact_collection_id": 2, "tag": "prod"}
    expected_artifact_filter = {"metadata.owner": "alice", "version": 3}

    assert json.loads(gql_vars["registryFilter"]) == expected_registry_filter
    assert json.loads(gql_vars["collectionFilter"]) == expected_collection_filter
    assert json.loads(gql_vars["artifactFilter"]) == expected_artifact_filter
    service_api.feature_enabled.assert_called_once()


def test_versions_rejects_advanced_field_in_basic_mode(service_api: MagicMock):
    field = "project_id"

    with raises(ValueError, match=rf"Invalid filter field.*{field}"):
        Versions(service_api, organization="org", registry_filter={field: 1})


def test_versions_rejects_basic_field_in_advanced_mode(
    service_api: MagicMock,
    enable_advanced_search: None,
):
    field = "description"

    with raises(ValueError, match=rf"Invalid filter field.*{field}"):
        Versions(service_api, organization="org", registry_filter={field: 1})


def test_paginators_reject_unknown_filter_fields(
    service_api: MagicMock,
):
    bad_filter = {"not_a_valid_field": 1}

    with raises(ValueError, match="Invalid filter field"):
        Registries(service_api, organization="org", filter=bad_filter)
    with raises(ValueError, match="Invalid filter field"):
        Collections(service_api, organization="org", collection_filter=bad_filter)
    with raises(ValueError, match="Invalid filter field"):
        Versions(service_api, organization="org", artifact_filter=bad_filter)


def test_advanced_search_disabled_without_server_capability(service_api: MagicMock):
    service_api.feature_enabled.return_value = False

    assert advanced_search_enabled(service_api, "org") is False
    service_api.execute_graphql.assert_not_called()


def test_advanced_search_error_logs_and_falls_back(
    service_api: MagicMock,
    wandb_caplog,
):
    service_api.feature_enabled.return_value = True
    service_api.execute_graphql.side_effect = RuntimeError("network down")

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert advanced_search_enabled(service_api, "org") is False

    assert "Failed to fetch advanced registry features" in wandb_caplog.text


@mark.parametrize("cls", [Registries, Collections])
@mark.parametrize(
    ("arg", "expected"),
    [
        # Unsigned fields default to ascending ("+")
        ("name", "+name"),
        ("updated_at", "+updated_at"),
        # Explicit signs are retained
        ("+name", "+name"),
        ("-created_at", "-created_at"),
        # Explicit None is untouched
        (None, None),
    ],
)
def test_paginator_with_valid_order(
    service_api: MagicMock,
    cls: type[RelayPaginator],
    arg: str,
    expected: str,
):
    """A supported `order` string is validated and normalized into the GraphQL variables."""
    paginator = cls(service_api=service_api, organization="org", order=arg)
    assert paginator.variables.get("order") == expected


@mark.parametrize("cls", [Registries, Collections])
def test_paginator_order_defaults_to_none(
    service_api: MagicMock, cls: type[RelayPaginator]
):
    """Omitting `order` leaves it unset in the GraphQL variables."""
    paginator = cls(service_api=service_api, organization="org")
    assert paginator.variables.get("order") is None


@mark.parametrize("cls", [Registries, Collections])
@mark.parametrize(
    "order",
    [
        # A field the paginator doesn't allow, with and without a sign.
        "unsupported_field",
        "-unsupported_field",
        "+unsupported_field",
        # Field names are currently case-sensitive
        "NAME",
        "+Name",
        "-cReated_At",
        # Invalid field names, ordering syntax, or both.
        "123name",
        "+123name",
        "-123name",
        "name desc",
        "multi\nline",
        "++name",
        "--name",
        "",
    ],
)
def test_paginator_with_invalid_order(
    service_api: MagicMock, cls: type[RelayPaginator], order: str
):
    """An unsupported or malformed `order` arg raises before any request."""
    with raises(ValueError):
        cls(service_api=service_api, organization="org", order=order)
