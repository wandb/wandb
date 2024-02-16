"""Test the config file overrides for run template parameters."""

import pytest
import yaml
from wandb.sdk.launch import template


@pytest.fixture
def yaml_config_file(tmpdir):
    """Create a YAML config file."""
    config = {"foo": "bar"}
    path = tmpdir / "config.yaml"
    with open(path, "w") as file:
        yaml.dump(config, file)
    return path


@pytest.fixture
def json_config_file(tmpdir):
    """Create a JSON config file."""
    config = {"foo": "bar"}
    path = tmpdir / "config.json"
    with open(path, "w") as file:
        yaml.dump(config, file)
    return path


def test_yaml_config_file_override(monkeypatch, yaml_config_file):
    monkeypatch.setenv(f"WANDB_OVERRIDE__{yaml_config_file.basename}", '{"foo": "baz"}')
    template.ConfigFile(yaml_config_file)
    assert yaml_config_file.read_text("utf-8") == "foo: baz\n"


def test_json_config_file_override(monkeypatch, json_config_file):
    monkeypatch.setenv(f"WANDB_OVERRIDE__{json_config_file.basename}", '{"foo": "baz"}')
    template.ConfigFile(json_config_file)
    assert json_config_file.read_text("utf-8") == '{\n  "foo": "baz"\n}'


def test_yaml_config_split_override(monkeypatch, yaml_config_file):
    monkeypatch.setenv(f"WANDB_OVERRIDE__{yaml_config_file.basename}_0", '{"foo":')
    monkeypatch.setenv(f"WANDB_OVERRIDE__{yaml_config_file.basename}_1", ' "qux"}')
    template.ConfigFile(yaml_config_file)
    assert yaml_config_file.read_text("utf-8") == "foo: qux\n"


def test_unsupported_config_file_extension():
    with pytest.raises(ValueError, match="Unsupported config file extension"):
        template.ConfigFile("config.toml")
