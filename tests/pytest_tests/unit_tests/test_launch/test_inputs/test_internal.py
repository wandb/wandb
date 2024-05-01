"""Test internal methods of the job input management sdk."""

from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.inputs.internal import (
    ConfigTmpDir,
    JobInputArguments,
    _publish_job_input,
    _split_on_unesc_dot,
    handle_config_file_input,
    handle_run_config_input,
)


@pytest.mark.parametrize(
    "path, expected",
    [
        (r"path", ["path"]),
        (r"path.with.dot", ["path", "with", "dot"]),
        (r"path\.with\.esc.dot", ["path.with.esc", "dot"]),
        (r"path\.with.esc\.dot", ["path.with", "esc.dot"]),
        (r"path.with\.esc.dot", ["path", "with.esc", "dot"]),
    ],
)
def test_split_on_unesc_dot(path, expected):
    """Test _split_on_unesc_dot function."""
    assert _split_on_unesc_dot(path) == expected


def test_split_on_unesc_dot_trailing_backslash():
    """Test _split_on_unesc_dot function with trailing backslash."""
    with pytest.raises(LaunchError):
        _split_on_unesc_dot("path\\")


def test_config_tmp_dir():
    """Test ConfigTmpDir class."""
    config_dir = ConfigTmpDir()
    assert config_dir.tmp_dir.is_dir()
    assert config_dir.configs_dir.is_dir()
    assert config_dir.tmp_dir != config_dir.configs_dir


def test_job_input_arguments():
    """Test JobInputArguments class."""
    arguments = JobInputArguments(
        include=["include"], exclude=["exclude"], file_path="path", run_config=True
    )
    assert arguments.include == ["include"]
    assert arguments.exclude == ["exclude"]
    assert arguments.file_path == "path"
    assert arguments.run_config is True


def test_publish_job_input(mocker):
    """Test _publish_job_input function."""
    run = mocker.MagicMock()
    run._backend.interface = mocker.MagicMock()
    arguments = JobInputArguments(
        include=["include"], exclude=["exclude"], file_path="path", run_config=True
    )
    _publish_job_input(arguments, run)
    run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=True,
        file_path="path",
    )


def test_handle_config_file_input(mocker):
    """Test handle_config_file_input function."""
    mocker.patch("wandb.sdk.launch.inputs.internal.override_file")
    mocker.patch("wandb.sdk.launch.inputs.internal.config_path_is_valid")
    mocker.patch("wandb.sdk.launch.inputs.internal.ConfigTmpDir")
    mocker.patch("wandb.sdk.launch.inputs.internal.shutil.copy")
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", None)
    with pytest.raises(NotImplementedError):
        handle_config_file_input("path", include=["include"], exclude=["exclude"])

    wandb_run = MagicMock()
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", wandb_run)
    handle_config_file_input("path", include=["include"], exclude=["exclude"])
    wandb_run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=False,
        file_path="path",
    )


def test_handle_run_config_input(mocker):
    """Test handle_run_config_input function."""
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", None)
    with pytest.raises(NotImplementedError):
        handle_run_config_input(include=["include"], exclude=["exclude"])

    wandb_run = mocker.MagicMock()
    wandb_run._backend.interface = mocker.MagicMock()
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", wandb_run)
    handle_run_config_input(include=["include"], exclude=["exclude"])
    wandb_run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=True,
        file_path="",
    )
