"""Test internal methods of the job input management sdk."""

import platform
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
    _prepare_schema,
    _publish_job_input,
    _replace_refs_and_allofs,
    _split_on_unesc_dot,
    _validate_schema,
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
        "title": "ExampleSchema",
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
        "title": "ExampleSchema",
        "type": "object",
    }


class DatasetEnum(str, Enum):
    cifar10 = "cifar10"
    cifar100 = "cifar100"


class Trainer(BaseModel):
    learning_rate: float = Field(description="Learning rate of the model")
    batch_size: int = Field(ge=1, le=256, description="Number of samples per batch")
    dataset: DatasetEnum = Field(description="Name of the dataset to use")


class ExampleSchema(BaseModel):
    trainer: Trainer


def test_validate_schema_pydantic_lists():
    class Item(BaseModel):
        name: str
        epochs: int = Field(ge=1)

    class GenericLists(BaseModel):
        # TODO: Only list of enums are supported for now
        # tags: list[str] = Field(min_length=0, max_length=10)
        # probs: list[float] = Field(min_length=1)
        # items: list[Item] = Field(min_length=1)
        # dicts: list[dict[str, str]] = Field(min_length=1)
        enums: list[DatasetEnum] = Field(min_length=1)
        enums_no_bounds: list[DatasetEnum] = Field()

    prepared_schema = _prepare_schema(GenericLists)

    props = prepared_schema["properties"]
    assert props["enums"]["type"] == "array"
    assert props["enums"]["items"]["type"] == "string"

    assert props["enums_no_bounds"]["type"] == "array"
    assert props["enums_no_bounds"]["items"]["type"] == "string"

    _validate_schema(prepared_schema)


def test_validate_schema_pydantic_sets():
    """Generic Pydantic sets map to JSON Schema arrays properly."""

    class Item(BaseModel):
        name: str
        epochs: int = Field(ge=1)

    class GenericSets(BaseModel):
        # TODO: Only set of enums are supported for now
        # tags: set[str] = Field(min_length=0, max_length=10)
        # probs: set[float] = Field(min_length=1)
        # items: set[Item] = Field(min_length=1)
        # dicts: set[dict[str, str]] = Field(min_length=1)
        enums: set[DatasetEnum] = Field(min_length=1)
        enums_no_bounds: set[DatasetEnum] = Field()

    prepared_schema = _prepare_schema(GenericSets)

    props = prepared_schema["properties"]
    assert props["enums"]["type"] == "array"
    assert props["enums"]["items"]["type"] == "string"

    assert props["enums_no_bounds"]["type"] == "array"
    assert props["enums_no_bounds"]["items"]["type"] == "string"

    _validate_schema(prepared_schema)


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
    sys.version_info < (3, 9),
    reason="Pydantic versions <2.4 doesn't support json schema",
)
@pytest.mark.skipif(
    platform.system().lower() == "windows",
    reason="Doesn't work on Windows",
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
        "path", include=["include"], exclude=["exclude"], schema=ExampleSchema
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


@pytest.mark.parametrize(
    "schema, expected",
    [
        # --- Passing cases ---
        # Basic test
        ({"type": "object", "properties": {"key1": {"type": "integer"}}}, []),
        # Test using all supported keys + nested schemas
        (
            {
                "type": "object",
                "properties": {
                    "key1": {"type": "integer", "minimum": 3, "exclusiveMaximum": 6.0},
                    "key2": {"type": "number", "exclusiveMinimum": 1.2, "maximum": 3},
                    "key3": {
                        "type": "object",
                        "properties": {
                            "key3": {
                                "type": "string",
                                "title": "My cool string",
                                "description": "It is cool",
                                "enum": ["value-1", "value-2"],
                            },
                            "key4": {"type": "integer", "enum": [3, 4, 5]},
                            "key5": {"type": "boolean"},
                        },
                    },
                },
            },
            [],
        ),
        # --- Secret format tests ---
        # Test basic secret field
        (
            {
                "type": "object",
                "properties": {
                    "api_key": {
                        "type": "string",
                        "format": "secret",
                        "title": "API Key",
                        "description": "Secret API key",
                    }
                },
            },
            [],
        ),
        # Test nested object with secret field
        (
            {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "secret_token": {
                                "type": "string",
                                "format": "secret",
                                "description": "Nested secret",
                            },
                            "public_key": {
                                "type": "string",
                                "description": "Public configuration",
                            },
                        },
                    }
                },
            },
            [],
        ),
        # Test multiple secret fields
        (
            {
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "format": "secret"},
                    "db_password": {"type": "string", "format": "secret"},
                    "regular_field": {"type": "string"},
                },
            },
            [],
        ),
        # --- Placeholder field tests ---
        # Test basic placeholder field
        (
            {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "placeholder": "Enter your username",
                        "title": "Username",
                        "description": "Your account username",
                    }
                },
            },
            [],
        ),
        # --- Label field tests ---
        # Test basic label field
        (
            {
                "type": "object",
                "properties": {
                    "api_key": {
                        "type": "string",
                        "label": "API Key",
                        "placeholder": "sk-...",
                        "required": True,
                        "format": "secret",
                    }
                },
            },
            [],
        ),
        # Test nested object with label and placeholder fields
        (
            {
                "type": "object",
                "properties": {
                    "database": {
                        "type": "object",
                        "label": "Database Configuration",
                        "properties": {
                            "host": {
                                "type": "string",
                                "label": "Database Host",
                                "placeholder": "localhost",
                                "description": "Database host",
                            },
                            "port": {
                                "type": "integer",
                                "label": "Database Port",
                                "placeholder": "5432",
                                "minimum": 1,
                            },
                        },
                    }
                },
            },
            [],
        ),
        # --- Required field tests ---
        # Test basic required field
        (
            {
                "type": "object",
                "properties": {
                    "api_key": {
                        "type": "string",
                        "required": True,
                        "title": "API Key",
                        "description": "Required API key",
                    },
                    "optional_field": {
                        "type": "string",
                        "required": False,
                        "description": "Optional field",
                    },
                },
            },
            [],
        ),
        # Test required field with different types
        (
            {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "required": True,
                        "minimum": 1,
                    },
                    "threshold": {
                        "type": "number",
                        "required": True,
                        "minimum": 0.0,
                    },
                    "active": {
                        "type": "boolean",
                        "required": False,
                    },
                },
            },
            [],
        ),
        # Test nested object with required fields
        (
            {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "required": True,
                                "description": "Configuration name",
                            },
                            "version": {
                                "type": "string",
                                "required": False,
                                "placeholder": "1.0.0",
                            },
                        },
                    }
                },
            },
            [],
        ),
        # --- Warning cases ---
        # Test using a float as a minimum for an integer
        (
            {
                "type": "object",
                "properties": {"key1": {"type": "integer", "minimum": 1.5}},
            },
            ["1.5 is not of type 'integer'"],
        ),
        # Test setting "minimum" on a type that doesn't support it
        (
            {
                "type": "object",
                "properties": {"key1": {"type": "string", "minimum": 1}},
            },
            ["Unevaluated properties are not allowed ('minimum' was unexpected)"],
        ),
        # Test using an unsupported key
        (
            {
                "type": "object",
                "properties": {"key1": {"type": "integer", "default": 5}},
            },
            ["Unevaluated properties are not allowed ('default' was unexpected)"],
        ),
        # --- Placeholder field tests for all types ---
        # Test placeholder on boolean field
        (
            {
                "type": "object",
                "properties": {
                    "field1": {
                        "type": "boolean",
                        "placeholder": "Enable this feature",
                    }
                },
            },
            [],
        ),
        # Test placeholder on array field
        (
            {
                "type": "object",
                "properties": {
                    "field1": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["a", "b", "c"],
                        },
                        "placeholder": "Select options...",
                    }
                },
            },
            [],
        ),
        # --- Invalid UI field tests ---
        # Test placeholder with wrong type (must be string)
        (
            {
                "type": "object",
                "properties": {
                    "field1": {
                        "type": "string",
                        "placeholder": 123,  # Should be string
                    }
                },
            },
            ["123 is not of type 'string'"],
        ),
        # Test label with wrong type (must be string)
        (
            {
                "type": "object",
                "properties": {
                    "field1": {
                        "type": "string",
                        "label": 456,  # Should be string
                    }
                },
            },
            ["456 is not of type 'string'"],
        ),
        # --- Array passing cases ---
        # Array: string enum multi-select with bounds and uniqueness
        (
            {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["a", "b", "c"],
                        },
                        "uniqueItems": True,
                        "minItems": 1,
                        "maxItems": 3,
                    }
                },
            },
            [],
        ),
        # Array: integer enum multi-select
        (
            {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {
                            "type": "integer",
                            "enum": [1, 2, 3],
                        },
                        "uniqueItems": True,
                    }
                },
            },
            [],
        ),
        # Array: number enum multi-select, nested inside object
        (
            {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "lrs": {
                                "type": "array",
                                "items": {
                                    "type": "number",
                                    "enum": [0.001, 0.01, 0.1],
                                },
                                "minItems": 1,
                            }
                        },
                    }
                },
            },
            [],
        ),
        # Array with label, placeholder and required fields
        (
            {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["dev", "prod", "test"],
                        },
                        "label": "Environment Tags",
                        "placeholder": "Select environment tags...",
                        "required": True,
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                    "optional_list": {
                        "type": "array",
                        "items": {
                            "type": "integer",
                            "enum": [1, 2, 3, 4, 5],
                        },
                        "label": "Optional Numbers",
                        "placeholder": "Choose numbers (optional)",
                        "required": False,
                    },
                },
            },
            [],
        ),
        # --- Array warning cases ---
        # Array warning: unsupported 'contains'
        (
            {
                "type": "object",
                "properties": {
                    "arr": {
                        "type": "array",
                        "contains": {"type": "number"},
                    }
                },
            },
            ["Unevaluated properties are not allowed ('contains' was unexpected)"],
        ),
        # Array warning: unsupported 'prefixItems'
        (
            {
                "type": "object",
                "properties": {
                    "tuple_like": {
                        "type": "array",
                        "prefixItems": [
                            {"type": "string"},
                            {"type": "number"},
                        ],
                    }
                },
            },
            ["Unevaluated properties are not allowed ('prefixItems' was unexpected)"],
        ),
        # Array warning: minItems wrong type
        (
            {
                "type": "object",
                "properties": {
                    "vals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1.5,
                    }
                },
            },
            ["1.5 is not of type 'integer'"],
        ),
    ],
)
def test_validate_schema(mocker, mock_wandb_log, schema, expected):
    """Test that valid schemas show no warnings, and invalid schemas do."""
    _validate_schema(schema)
    warns = "".join(mock_wandb_log._logs(mock_wandb_log._termwarn))
    for e in expected:
        assert e in warns
    if not expected:
        assert not warns
