from wandb.apis.public.registries import _inject_registry_prefix_in_name
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


def test_simple_name_transform():
    query = {"name": "model"}
    expected = {"name": f"{REGISTRY_PREFIX}model"}
    assert _inject_registry_prefix_in_name(query) == expected


def test_list_handling():
    query = {"$or": [{"name": "model1"}, {"name": "model2"}]}
    expected = {
        "$or": [
            {"name": f"{REGISTRY_PREFIX}model1"},
            {"name": f"{REGISTRY_PREFIX}model2"},
        ]
    }
    assert _inject_registry_prefix_in_name(query) == expected


def test_regex_skip_transform():
    query = {"name": {"$regex": "model.*"}}
    assert _inject_registry_prefix_in_name(query) == query


def test_mixed_types():
    query = {"name": "model", "id": 1, "description": None}
    expected = {
        "name": f"{REGISTRY_PREFIX}model",
        "id": 1,
        "description": None,
    }
    assert _inject_registry_prefix_in_name(query) == expected


def test_empty_or_non_dict_input():
    assert _inject_registry_prefix_in_name("string") == "string"
    assert _inject_registry_prefix_in_name({}) == {}
    assert _inject_registry_prefix_in_name(123) == 123
    assert _inject_registry_prefix_in_name(None) is None
    assert _inject_registry_prefix_in_name(True) is True


def test_nested_structure():
    query = {"name": {"$in": ["project1", "project2", {"$regex": "project3"}]}}
    expected = {
        "name": {
            "$in": [
                f"{REGISTRY_PREFIX}project1",
                f"{REGISTRY_PREFIX}project2",
                {"$regex": "project3"},
            ]
        }
    }
    assert _inject_registry_prefix_in_name(query) == expected
