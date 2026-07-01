from __future__ import annotations

from typing import TYPE_CHECKING

from pytest import fixture, mark, raises
from wandb.apis.public.registries._utils import (
    prepare_artifact_types_input,
    validate_registry_filter,
)
from wandb.apis.public.registries.registries_search import Collections, Registries
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX

if TYPE_CHECKING:
    from unittest.mock import Mock

    from pytest_mock import MockerFixture
    from wandb.apis.paginator import RelayPaginator


@mark.parametrize(
    "artifact_types, expected_output",
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


def test_simple_name_transform():
    query = {"name": "model"}
    expected = {"name": f"{REGISTRY_PREFIX}model"}
    assert validate_registry_filter(query) == expected

    query = {"name": f"{REGISTRY_PREFIX}model"}
    expected = {"name": f"{REGISTRY_PREFIX}model"}
    assert validate_registry_filter(query) == expected


def test_list_handling():
    query = {"$or": [{"name": "model1"}, {"tag": "prod"}]}
    expected = {
        "$or": [
            {"name": f"{REGISTRY_PREFIX}model1"},
            {"tag": "prod"},
        ]
    }
    assert validate_registry_filter(query) == expected


def test_regex_skip_transform():
    query = {"name": {"$regex": "model.*"}}
    assert validate_registry_filter(query) == query


def test_mixed_types():
    query = {"id": 1, "name": "model", "description": None}
    expected = {
        "id": 1,
        "name": f"{REGISTRY_PREFIX}model",
        "description": None,
    }
    assert validate_registry_filter(query) == expected


@mark.parametrize(
    "bad_filter",
    ["string", {}, 123, None, True],
)
def test_empty_or_non_dict_input(bad_filter):
    assert validate_registry_filter(bad_filter) == bad_filter


def test_nested_structure():
    query = {
        "name": {
            "$in": [
                "project1",
                f"{REGISTRY_PREFIX}project2",
                {"$regex": "project3"},
            ]
        }
    }
    expected = {
        "name": {
            "$in": [
                f"{REGISTRY_PREFIX}project1",
                f"{REGISTRY_PREFIX}project2",
                {"$regex": "project3"},
            ]
        }
    }
    assert validate_registry_filter(query) == expected


@fixture
def mock_service_api(mocker: MockerFixture) -> Mock:
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


@mark.parametrize("paginator_cls", [Registries, Collections])
@mark.parametrize(
    "arg, expected",
    [
        # An unsigned field defaults to ascending ("+"); an explicit sign is kept.
        ("name", "+name"),
        ("+name", "+name"),
        ("-created_at", "-created_at"),
        ("updated_at", "+updated_at"),
    ],
)
def test_paginator_normalizes_order(
    paginator_cls: type[RelayPaginator], arg: str, expected: str, mock_service_api: Mock
):
    """A supported `order` string is validated and normalized into the GraphQL variables."""
    it = paginator_cls(service_api=mock_service_api, organization="org", order=arg)
    assert it.variables["order"] == expected


@mark.parametrize("paginator_cls", [Registries, Collections])
def test_paginator_order_defaults_to_none(
    paginator_cls: type[RelayPaginator], mock_service_api: Mock
):
    """Omitting `order` leaves it unset in the GraphQL variables."""
    it = paginator_cls(service_api=mock_service_api, organization="org")
    assert it.variables["order"] is None


@mark.parametrize("paginator_cls", [Registries, Collections])
@mark.parametrize(
    "order",
    [
        # A field the paginator doesn't allow, with and without a sign.
        "unsupported_field",
        "-unsupported_field",
        # A valid field, but allowed-field matching is case-sensitive.
        "Name",
        # Valid fields wrapped in strings that don't match the sign+field grammar.
        "name desc",
        "++name",
        "",
    ],
)
def test_paginator_rejects_invalid_order(
    paginator_cls: type[RelayPaginator], order: str, mock_service_api: Mock
):
    """An unsupported or malformed `order` arg raises before any request."""
    with raises(ValueError):
        paginator_cls(service_api=mock_service_api, organization="org", order=order)
