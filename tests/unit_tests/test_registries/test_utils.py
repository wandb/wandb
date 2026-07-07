from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pytest import fixture, mark, param, raises
from wandb.apis.public.registries._utils import (
    prepare_artifact_types_input,
    prepare_registry_filter,
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


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


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


# TODO: Fix this, overparameterized by AI
@mark.parametrize(
    ("cls", "filter_arg", "filter_var", "raw", "expected"),
    [
        param(
            Registries,
            "filter",
            "filters",
            {
                "name": {
                    "$in": [
                        "project1",
                        f"{REGISTRY_PREFIX}project2",
                        {"$regex": "project3"},
                    ]
                },
                "description": None,
                "created_at": 1,
                "updated_at": {"$gte": "2021-01-01T00:00:00Z"},
            },
            {
                "name": {
                    "$in": [
                        f"{REGISTRY_PREFIX}project1",
                        f"{REGISTRY_PREFIX}project2",
                        {"$regex": "project3"},
                    ]
                },
                "description": None,
                "created_at": 1,
                "updated_at": {"$gte": "2021-01-01T00:00:00Z"},
            },
            id="registries-filter",
        ),
        param(
            Collections,
            "registry_filter",
            "registryFilter",
            {"name": "model"},
            {"name": f"{REGISTRY_PREFIX}model"},
            id="collections-registry-filter",
        ),
        param(
            Collections,
            "collection_filter",
            "collectionFilter",
            {
                "name": "collection",
                "tag": "prod",
                "description": None,
                "created_at": 1,
                "updated_at": 2,
            },
            {
                "name": "collection",
                "tag": "prod",
                "description": None,
                "created_at": 1,
                "updated_at": 2,
            },
            id="collections-collection-filter",
        ),
        param(
            Versions,
            "registry_filter",
            "registryFilter",
            {"name": "model"},
            {"name": f"{REGISTRY_PREFIX}model"},
            id="versions-registry-filter",
        ),
        param(
            Versions,
            "collection_filter",
            "collectionFilter",
            {"tag": "prod"},
            {"tag": "prod"},
            id="versions-collection-filter",
        ),
        param(
            Versions,
            "artifact_filter",
            "artifactFilter",
            {
                "tag": "prod",
                "alias": "latest",
                "created_at": 1,
                "updated_at": 2,
                "metadata.foo": 1,
            },
            {
                "tag": "prod",
                "alias": "latest",
                "created_at": 1,
                "updated_at": 2,
                "metadata.foo": 1,
            },
            id="versions-artifact-filter",
        ),
    ],
)
def test_paginator_with_valid_filter(
    service_api: MagicMock,
    cls: type[Registries | Collections | Versions],
    filter_arg: str,
    filter_var: str,
    raw: dict[str, Any],
    expected: dict[str, Any],
):
    paginator = cls(service_api=service_api, organization="org", **{filter_arg: raw})
    assert json.loads(paginator.variables[filter_var]) == expected


def test_paginators_with_invalid_filter(service_api: MagicMock):
    bad_filter = {"not_a_valid_field": 1}
    expected_msg = r"(?i)invalid filter field"

    # Registries
    with raises(ValueError, match=expected_msg):
        Registries(service_api, organization="org", filter=bad_filter)

    # Collections
    with raises(ValueError, match=expected_msg):
        Collections(service_api, organization="org", registry_filter=bad_filter)
    with raises(ValueError, match=expected_msg):
        Collections(service_api, organization="org", collection_filter=bad_filter)
    with raises(ValueError, match=expected_msg):
        Collections(
            service_api,
            organization="org",
            registry_filter=bad_filter,
            collection_filter=bad_filter,
        )

    # Versions
    with raises(ValueError, match=expected_msg):
        Versions(service_api, organization="org", registry_filter=bad_filter)
    with raises(ValueError, match=expected_msg):
        Versions(service_api, organization="org", collection_filter=bad_filter)
    with raises(ValueError, match=expected_msg):
        Versions(service_api, organization="org", artifact_filter=bad_filter)
    with raises(ValueError, match=expected_msg):
        Versions(
            service_api,
            organization="org",
            registry_filter=bad_filter,
            collection_filter=bad_filter,
            artifact_filter=bad_filter,
        )


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
