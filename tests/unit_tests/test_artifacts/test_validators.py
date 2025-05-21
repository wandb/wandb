import pytest
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    RESERVED_ARTIFACT_TYPE_PREFIX,
    validate_artifact_type,
    validate_project_name,
)


@pytest.mark.parametrize(
    "project_name, expected_output",
    [
        ("my-project-?", "cannot contain characters: '?'"),
        ("my-project-\n", "cannot contain characters: '\\\\n'"),
        ("my-?:/-project", "cannot contain characters: '/', ':', '?'"),
        (REGISTRY_PREFIX + "a" * 128, "Invalid registry name"),
        ("p" * 129, "must be 128 characters or less"),
        ("", "Project name cannot be empty"),
        (REGISTRY_PREFIX, "Registry name cannot be empty"),
    ],
)
def test_validate_project_name_invalid(project_name, expected_output):
    with pytest.raises(ValueError, match=expected_output):
        validate_project_name(project_name)


@pytest.mark.parametrize(
    "project_name",
    [
        "my-project",
        "m",
        "wandb-registry-a",
        "p" * 127,
    ],
)
def test_validate_project_name_valid(project_name):
    validate_project_name(project_name)


@pytest.mark.parametrize(
    "artifact_type, name",
    [
        (RESERVED_ARTIFACT_TYPE_PREFIX + "invalid", "name"),
        ("job", "name"),
        ("run_table", "run-name"),
        ("code", "source-name"),
    ],
)
def test_validate_artifact_type_invalid(artifact_type, name):
    with pytest.raises(ValueError, match="is reserved for internal use"):
        validate_artifact_type(artifact_type, name)


@pytest.mark.parametrize(
    "artifact_type, name",
    [
        ("dataset", "name"),
        ("wandbtype", "name"),
        ("code", "name"),
        ("run_table", "name"),
    ],
)
def test_validate_artifact_type_valid(artifact_type, name):
    assert validate_artifact_type(artifact_type, name) == artifact_type
