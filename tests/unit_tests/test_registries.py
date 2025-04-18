import pytest
from wandb.apis.public.registries import _ensure_registry_prefix_on_names
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


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
