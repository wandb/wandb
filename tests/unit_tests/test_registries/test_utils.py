import pytest
from wandb.apis.public.registries.utils import (
    _ensure_registry_prefix_on_names,
    _format_gql_artifact_types_input,
)
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


@pytest.mark.parametrize(
    "new_artifact_types, existing_artifact_types, expected_output",
    [
        (None, None, []),
        (None, ["a"], []),
        ([], None, []),
        ([], ["a"], []),
        (["a", "b"], None, [{"name": "a"}, {"name": "b"}]),
        (["a", "b"], [], [{"name": "a"}, {"name": "b"}]),
        (["a", "b", "c"], ["b", "d"], [{"name": "a"}, {"name": "c"}]),
        (["a", "b"], ["a", "b", "c"], []),
        (["a", "b"], ["c", "d"], [{"name": "a"}, {"name": "b"}]),
    ],
)
def test_format_gql_artifact_types_input(
    new_artifact_types,
    existing_artifact_types,
    expected_output,
):
    """Test the format_gql_artifact_types_input function."""
    # Assuming validate_artifact_types_list passes through valid lists
    # and returns empty list for None/empty list input.
    result = _format_gql_artifact_types_input(
        new_artifact_types=new_artifact_types,
        existing_artifact_types=existing_artifact_types,
    )
    assert result == expected_output


@pytest.mark.parametrize(
    "artifact_types, expected_output",
    [
        # Valid case
        (["my-valid-type_123"], [{"name": "my-valid-type_123"}]),
        # Invalid characters
        (
            ["valid_type", "invalid:::"],
            ValueError,
        ),
        (
            ["invalid/type"],
            ValueError,
        ),
        (
            ["invalid:type"],
            ValueError,
        ),
        # Too long
        (["a" * 129], ValueError),
    ],
)
def test_format_gql_artifact_types_input_validation(artifact_types, expected_output):
    """Test artifact type name validation within format_gql_artifact_types_input."""
    if isinstance(expected_output, ValueError):
        with pytest.raises(ValueError):
            _format_gql_artifact_types_input(new_artifact_types=artifact_types)
    else:
        result = _format_gql_artifact_types_input(new_artifact_types=artifact_types)
        assert result == expected_output


def test_simple_name_transform():
    query = {"name": "model"}
    expected = {"name": f"{REGISTRY_PREFIX}model"}
    assert _ensure_registry_prefix_on_names(query) == expected

    query = {"name": f"{REGISTRY_PREFIX}model"}
    expected = {"name": f"{REGISTRY_PREFIX}model"}
    assert _ensure_registry_prefix_on_names(query) == expected


def test_list_handling():
    query = {"$or": [{"name": "model1"}, {"tag": "prod"}]}
    expected = {
        "$or": [
            {"name": f"{REGISTRY_PREFIX}model1"},
            {"tag": "prod"},
        ]
    }
    assert _ensure_registry_prefix_on_names(query) == expected


def test_regex_skip_transform():
    query = {"name": {"$regex": "model.*"}}
    assert _ensure_registry_prefix_on_names(query) == query


def test_mixed_types():
    query = {"id": 1, "name": "model", "description": None}
    expected = {
        "id": 1,
        "name": f"{REGISTRY_PREFIX}model",
        "description": None,
    }
    assert _ensure_registry_prefix_on_names(query) == expected


@pytest.mark.parametrize(
    "bad_filter",
    ["string", {}, 123, None, True],
)
def test_empty_or_non_dict_input(bad_filter):
    assert _ensure_registry_prefix_on_names(bad_filter) == bad_filter


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
    assert _ensure_registry_prefix_on_names(query) == expected
