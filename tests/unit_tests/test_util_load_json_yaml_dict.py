"""Tests for wandb.util.load_json_yaml_dict()."""

from wandb.util import load_json_yaml_dict

YAML_CONTENT = "key: value\nnumber: 7\n"
INLINE_JSON = '{"key": "value", "number": 7}'
EXPECTED = {"key": "value", "number": 7}


def test_load_json_yaml_dict_yml(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(YAML_CONTENT)

    assert load_json_yaml_dict(str(config)) == EXPECTED


def test_load_json_yaml_dict_yaml(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(YAML_CONTENT)

    assert load_json_yaml_dict(str(config)) == EXPECTED


def test_load_json_yaml_dict_json(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(INLINE_JSON)

    assert load_json_yaml_dict(str(config)) == EXPECTED


def test_load_json_yaml_dict_inline_json():
    assert load_json_yaml_dict(INLINE_JSON) == EXPECTED


def test_load_json_yaml_dict_bad_input():
    assert load_json_yaml_dict("not a config") is None
