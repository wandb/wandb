from types import SimpleNamespace

from wandb.sdk.lib.proto_util import dict_from_proto_list


def _item(value_json, key="", nested_key=()):
    # dict_from_proto_list only reads .key, .nested_key and .value_json off
    # each proto item, so a lightweight stand-in is enough to exercise it.
    return SimpleNamespace(key=key, nested_key=list(nested_key), value_json=value_json)


def test_empty_list_returns_empty_dict():
    assert dict_from_proto_list([]) == {}


def test_flat_keys_parse_value_json():
    result = dict_from_proto_list([_item("1", key="a"), _item('"hi"', key="b")])
    assert result == {"a": 1, "b": "hi"}


def test_nested_key_builds_nested_dict():
    assert dict_from_proto_list([_item("2", nested_key=["x", "y"])]) == {"x": {"y": 2}}


def test_shared_prefix_is_merged():
    result = dict_from_proto_list(
        [_item("1", nested_key=["a", "b"]), _item("2", nested_key=["a", "c"])]
    )
    assert result == {"a": {"b": 1, "c": 2}}


def test_json_value_is_deserialized():
    result = dict_from_proto_list([_item('{"k": [1, 2]}', key="m")])
    assert result == {"m": {"k": [1, 2]}}
