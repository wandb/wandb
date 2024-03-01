"""Test the config file overrides for run template parameters."""

import json

import pytest
import yaml
from wandb.sdk.launch import template
from wandb.sdk.launch.template.config_file import FILE_OVERRIDE_ENV_VAR, FileOverrides


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
    config = json.dumps({f"../{yaml_config_file.basename}": {"foo": "baz"}})
    monkeypatch.setenv(
        FILE_OVERRIDE_ENV_VAR,
        config,
    )
    FileOverrides().load()
    template.ConfigFile(yaml_config_file)
    assert yaml_config_file.read_text("utf-8") == "foo: baz\n"


def test_json_config_file_override(monkeypatch, json_config_file):
    config = json.dumps({f"../{json_config_file.basename}": {"foo": "baz"}})
    monkeypatch.setenv(
        FILE_OVERRIDE_ENV_VAR,
        config,
    )
    FileOverrides().load()
    template.ConfigFile(json_config_file)
    assert json_config_file.read_text("utf-8") == '{\n  "foo": "baz"\n}'


def test_yaml_config_split_override(monkeypatch, yaml_config_file):
    config = json.dumps({f"../{yaml_config_file.basename}": {"foo": "baz"}})
    p1, p2 = config[:10], config[10:]
    monkeypatch.setenv(
        f"{FILE_OVERRIDE_ENV_VAR}_0",
        p1,
    )
    monkeypatch.setenv(
        f"{FILE_OVERRIDE_ENV_VAR}_1",
        p2,
    )
    FileOverrides().load()
    template.ConfigFile(yaml_config_file)
    assert yaml_config_file.read_text("utf-8") == "foo: baz\n"
