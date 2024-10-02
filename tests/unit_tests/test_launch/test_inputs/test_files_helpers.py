import json

import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.inputs.files import (
    FileOverrides,
    config_path_is_valid,
    override_file,
)


@pytest.fixture
def fresh_config_singleton():
    """Fixture to reset the config singleton."""
    FileOverrides._instance = None


def test_override_file_basic(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test override_file function."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES",
        json.dumps({"config.json": {"key": "new_value"}}),
    )

    override_file("config.json")

    assert path.read_text() == json.dumps({"key": "new_value"}, indent=2)


def test_override_file_nested(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test override_file function with nested dictionary."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": {"nested_key": "value"}}')
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES",
        json.dumps({"config.json": {"key": {"nested_key": "new_value"}}}),
    )

    override_file("config.json")

    assert path.read_text() == json.dumps(
        {"key": {"nested_key": "new_value"}}, indent=2
    )


def test_override_file_split_env_var(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test override_file function with split env var."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')
    override_dict = json.dumps({"config.json": {"key": "new_value"}})
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES_0",
        override_dict[: len(override_dict) // 2],
    )
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES_1",
        override_dict[len(override_dict) // 2 :],
    )

    override_file("config.json")

    assert path.read_text() == json.dumps({"key": "new_value"}, indent=2)


def test_override_file_yaml(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test override_file function with YAML."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text("key: value")
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES",
        json.dumps({"config.yaml": {"key": "new_value"}}),
    )

    override_file("config.yaml")

    assert path.read_text() == "key: new_value\n"


def test_override_file_unknown_extension(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test override_file function with unknown extension."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.unknown"
    path.write_text('{"key": "value"}')
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES",
        json.dumps({"config.unknown": {"key": "new_value"}}),
    )

    with pytest.raises(LaunchError):
        override_file("config.unknown")


def test_file_overrides_invalid_json(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test FileOverrides with invalid JSON."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')
    monkeypatch.setenv(
        "WANDB_LAUNCH_FILE_OVERRIDES", '{"config.json": {"key": "new_value"}'
    )

    with pytest.raises(LaunchError):
        override_file("config.json")


def test_file_overrides_non_dict(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test FileOverrides with non-dictionary value."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')
    monkeypatch.setenv("WANDB_LAUNCH_FILE_OVERRIDES", '["config.json"]')

    with pytest.raises(LaunchError):
        override_file("config.json")


def test_config_path_is_valid(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test config_path_is_valid function."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')

    config_path_is_valid("config.json")


def test_config_path_is_valid_invalid(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test config_path_is_valid function with invalid path."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(LaunchError):
        config_path_is_valid("config.json")


def test_config_path_is_valid_not_file(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test config_path_is_valid function with non-file path."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config"
    path.mkdir()

    with pytest.raises(LaunchError):
        config_path_is_valid("config")


def test_config_path_is_valid_absolute(
    monkeypatch,
    tmp_path,
    fresh_config_singleton,
):
    """Test config_path_is_valid function with absolute path."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"key": "value"}')

    with pytest.raises(LaunchError):
        config_path_is_valid(str(path))
