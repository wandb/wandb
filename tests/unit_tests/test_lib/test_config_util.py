from types import SimpleNamespace

from wandb.sdk.lib.config_util import (
    dict_from_proto_list,
    dict_no_value_from_proto_list,
    dict_strip_value_dict,
)


def _item(key, value_json):
    # These helpers only read .key and .value_json off each proto item.
    return SimpleNamespace(key=key, value_json=value_json)


def test_dict_from_proto_list_wraps_values_with_desc():
    result = dict_from_proto_list([_item("a", "1"), _item("b", '"x"')])
    assert result == {
        "a": {"desc": None, "value": 1},
        "b": {"desc": None, "value": "x"},
    }


def test_dict_strip_value_dict():
    config = {"a": {"value": 1, "desc": None}, "b": {"value": 2}}
    assert dict_strip_value_dict(config) == {"a": 1, "b": 2}


def test_dict_no_value_keeps_value_dicts():
    result = dict_no_value_from_proto_list([_item("a", '{"value": 5}')])
    assert result == {"a": 5}


def test_dict_no_value_skips_non_dict_values():
    assert dict_no_value_from_proto_list([_item("a", "7")]) == {}


def test_dict_no_value_skips_dict_without_value_key():
    assert dict_no_value_from_proto_list([_item("a", '{"x": 1}')]) == {}
