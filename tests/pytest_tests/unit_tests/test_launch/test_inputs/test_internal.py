"""Test internal methods of the job input management sdk."""

import sys
from enum import Enum
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.inputs.internal import (
    ConfigTmpDir,
    JobInputArguments,
    StagedLaunchInputs,
    _publish_job_input,
    _replace_refs_and_allofs,
    _split_on_unesc_dot,
    handle_config_file_input,
    handle_run_config_input,
)


@pytest.fixture
def reset_staged_inputs():
    StagedLaunchInputs._instance = None


@pytest.fixture
def test_json_schema():
    return {
        "$defs": {
            "DatasetEnum": {
                "enum": ["cifar10", "cifar100"],
                "title": "DatasetEnum",
                "type": "string",
            },
            "Trainer": {
                "properties": {
                    "learning_rate": {
                        "description": "Learning rate of the model",
                        "title": "Learning Rate",
                        "type": "number",
                    },
                    "batch_size": {
                        "description": "Number of samples per batch",
                        "maximum": 256,
                        "minimum": 1,
                        "title": "Batch Size",
                        "type": "integer",
                    },
                    "dataset": {
                        "allOf": [{"$ref": "#/$defs/DatasetEnum"}],
                        "description": "Name of the dataset to use",
                    },
                },
                "required": ["learning_rate", "batch_size", "dataset"],
                "title": "Trainer",
                "type": "object",
            },
        },
        "properties": {"trainer": {"$ref": "#/$defs/Trainer"}},
        "required": ["trainer"],
        "title": "TestSchema",
        "type": "object",
    }


@pytest.fixture
def expected_json_schema():
    return {
        "properties": {
            "trainer": {
                "properties": {
                    "learning_rate": {
                        "description": "Learning rate of the model",
                        "title": "Learning Rate",
                        "type": "number",
                    },
                    "batch_size": {
                        "description": "Number of samples per batch",
                        "maximum": 256,
                        "minimum": 1,
                        "title": "Batch Size",
                        "type": "integer",
                    },
                    "dataset": {
                        "enum": ["cifar10", "cifar100"],
                        "title": "DatasetEnum",
                        "type": "string",
                        "description": "Name of the dataset to use",
                    },
                },
                "required": ["learning_rate", "batch_size", "dataset"],
                "title": "Trainer",
                "type": "object",
            }
        },
        "required": ["trainer"],
        "title": "TestSchema",
        "type": "object",
    }


class DatasetEnum(str, Enum):
    cifar10 = "cifar10"
    cifar100 = "cifar100"


class Trainer(BaseModel):
    learning_rate: float = Field(description="Learning rate of the model")
    batch_size: int = Field(ge=1, le=256, description="Number of samples per batch")
    dataset: DatasetEnum = Field(description="Name of the dataset to use")


class TestSchema(BaseModel):
    trainer: Trainer


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
        input_schema=None,
        file_path="path",
    )


def test_replace_refs_and_allofs(test_json_schema, expected_json_schema):
    defs = test_json_schema.pop("$defs")
    resp = _replace_refs_and_allofs(test_json_schema, defs)
    assert resp == expected_json_schema


def test_handle_config_file_input(mocker):
    """Test handle_config_file_input function."""
    mocker.patch("wandb.sdk.launch.inputs.internal.override_file")
    mocker.patch("wandb.sdk.launch.inputs.internal.config_path_is_valid")
    mocker.patch("wandb.sdk.launch.inputs.internal.ConfigTmpDir")
    mocker.patch("wandb.sdk.launch.inputs.internal.shutil.copy")

    wandb_run = MagicMock()
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", wandb_run)
    handle_config_file_input("path", include=["include"], exclude=["exclude"])
    wandb_run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=False,
        input_schema=None,
        file_path="path",
    )


@pytest.mark.skipif(
    sys.version_info <= (3, 8),
    reason="Pydantic versions <2.4 doesn't support json schema",
)
def test_handle_config_file_input_pydantic(
    mocker,
    expected_json_schema,
):
    """Test handle_config_file_input function with a Pydantic model schema."""
    mocker.patch("wandb.sdk.launch.inputs.internal.override_file")
    mocker.patch("wandb.sdk.launch.inputs.internal.config_path_is_valid")
    mocker.patch("wandb.sdk.launch.inputs.internal.ConfigTmpDir")
    mocker.patch("wandb.sdk.launch.inputs.internal.shutil.copy")

    wandb_run = MagicMock()
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", wandb_run)
    handle_config_file_input(
        "path", include=["include"], exclude=["exclude"], schema=TestSchema
    )
    wandb_run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=False,
        input_schema=expected_json_schema,
        file_path="path",
    )


def test_handle_run_config_input(mocker):
    """Test handle_run_config_input function."""
    wandb_run = mocker.MagicMock()
    wandb_run._backend.interface = mocker.MagicMock()
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", wandb_run)
    handle_run_config_input(include=["include"], exclude=["exclude"])
    wandb_run._backend.interface.publish_job_input.assert_called_once_with(
        include_paths=[["include"]],
        exclude_paths=[["exclude"]],
        run_config=True,
        input_schema=None,
        file_path="",
    )


def test_handle_config_file_input_staged(mocker, reset_staged_inputs):
    """Test that config file input is staged when run is not available."""
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", None)
    mocker.patch("wandb.sdk.launch.inputs.internal.override_file")
    mocker.patch("wandb.sdk.launch.inputs.internal.config_path_is_valid")
    mocker.patch("wandb.sdk.launch.inputs.internal.ConfigTmpDir")
    mocker.patch("wandb.sdk.launch.inputs.internal.shutil.copy")

    handle_config_file_input("path", include=["include"], exclude=["exclude"])
    staged_inputs = StagedLaunchInputs()._staged_inputs
    assert len(staged_inputs) == 1
    config_file = staged_inputs[0]
    assert config_file.include == ["include"]
    assert config_file.exclude == ["exclude"]
    assert config_file.file_path == "path"
    assert config_file.run_config is False


def test_handle_run_config_input_staged(mocker, reset_staged_inputs):
    """Test that run config input is staged when run is not available."""
    mocker.patch("wandb.sdk.launch.inputs.internal.wandb.run", None)
    handle_run_config_input(include=["include"], exclude=["exclude"])
    staged_inputs = StagedLaunchInputs()._staged_inputs
    assert len(staged_inputs) == 1
    run_config = staged_inputs[0]
    assert run_config.include == ["include"]
    assert run_config.exclude == ["exclude"]
    assert run_config.file_path is None
    assert run_config.run_config is True
