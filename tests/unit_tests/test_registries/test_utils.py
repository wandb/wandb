from __future__ import annotations

from typing import TYPE_CHECKING

from pytest import fixture, mark, param, raises
from wandb.apis.public.registries._utils import (
    prepare_artifact_types_input,
    prepare_registry_filter,
)
from wandb.apis.public.registries.registries_search import Collections, Registries
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture
    from wandb.apis.paginator import RelayPaginator


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
                        {"$regex": "project3"},
                    ]
                }
            },
            {
                "name": {
                    "$in": [
                        f"{REGISTRY_PREFIX}project1",
                        f"{REGISTRY_PREFIX}project2",
                        {"$regex": "project3"},
                    ]
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


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


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
        # Field names are normalized to lowercase
        ("NAME", "+name"),
        ("+Name", "+name"),
        ("-cReated_At", "-created_at"),
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
        # Invalid field names, ordering syntax, or both.
        "123name",
        "+123name",
        "-123name",
        "name desc",
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
