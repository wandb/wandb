from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

from pydantic import TypeAdapter
from pytest import fixture, mark, param, raises
from wandb._filters import FilterValidator
from wandb._pydantic import FilterDict
from wandb.apis.public.registries._utils import (
    prefix_registry_name,
    prepare_artifact_types_input,
)
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture
    from wandb.apis.paginator import RelayPaginator


REGISTRY_FILTER_ADAPTER = TypeAdapter(
    Annotated[
        FilterDict,
        FilterValidator(transforms={"name": prefix_registry_name}),
    ]
)


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


@fixture
def disable_advanced_search(service_api: MagicMock) -> None:
    service_api.feature_enabled.return_value = False
    service_api.execute_graphql.return_value = None


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
        param({}, {}, id="empty-dict"),
    ],
)
def test_registry_filter_normalization(raw, expected):
    assert REGISTRY_FILTER_ADAPTER.validate_python(raw) == expected


def test_basic_paginators_normalize_filters(service_api: MagicMock):
    registries = Registries(
        service_api,
        organization="org",
        filter={"name": "model", "id": 1},
    )
    collections = Collections(
        service_api,
        organization="org",
        registry_filter={"name": "model"},
        collection_filter={"collection_id": 2, "tag": "prod"},
    )

    expected_registries_filter = {"name": f"{REGISTRY_PREFIX}model", "id": 1}
    expected_registry_filter = {"name": f"{REGISTRY_PREFIX}model"}
    expected_collection_filter = {"artifact_collection_id": 2, "tag": "prod"}

    assert json.loads(registries.variables["filters"]) == expected_registries_filter
    assert (
        json.loads(collections.variables["registryFilter"]) == expected_registry_filter
    )
    assert (
        json.loads(collections.variables["collectionFilter"])
        == expected_collection_filter
    )


def test_versions_uses_basic_filter_fields(
    service_api: MagicMock,
    disable_advanced_search: None,
):
    versions = Versions(
        service_api,
        organization="org",
        registry_filter={"name": "model", "id": 1},
        collection_filter={"collection_id": 2, "tag": "prod"},
        artifact_filter={
            "metadata.owner": "alice",
            "version": 3,
        },
    )

    gql_vars = versions.variables

    expected_registry_filter = {"name": f"{REGISTRY_PREFIX}model", "id": 1}
    expected_collection_filter = {"artifact_collection_id": 2, "tag": "prod"}
    expected_artifact_filter = {"metadata.owner": "alice", "version": 3}

    assert json.loads(gql_vars["registryFilter"]) == expected_registry_filter
    assert json.loads(gql_vars["collectionFilter"]) == expected_collection_filter
    assert json.loads(gql_vars["artifactFilter"]) == expected_artifact_filter


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
