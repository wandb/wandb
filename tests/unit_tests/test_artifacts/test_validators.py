import pytest
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    RESERVED_ARTIFACT_TYPE_PREFIX,
    ArtifactPath,
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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "name",
            ArtifactPath(prefix=None, project=None, name="name"),
        ),
        (
            "project/name",
            ArtifactPath(prefix=None, project="project", name="name"),
        ),
        (
            "entity/project/name",
            ArtifactPath(prefix="entity", project="project", name="name"),
        ),
        (
            "entity/project/name:v0",
            ArtifactPath(prefix="entity", project="project", name="name:v0"),
        ),
        (
            "project/name:v0",
            ArtifactPath(prefix=None, project="project", name="name:v0"),
        ),
        (
            "name:alias/with/slashes",
            ArtifactPath(prefix=None, project=None, name="name:alias/with/slashes"),
        ),
    ],
)
def test_artifact_path_from_valid_str(path: str, expected: ArtifactPath):
    """Check that the ArtifactPath.from_str() method correctly parses valid artifact paths."""
    assert ArtifactPath.from_str(path) == expected


def test_artifact_path_from_invalid_str():
    """Check that the ArtifactPath.from_str() method correctly raises an error for invalid artifact paths."""
    with pytest.raises(ValueError):
        ArtifactPath.from_str("path/with/too/many/parts")


@pytest.mark.parametrize(
    "path_str",
    [
        "name",
        "project/name",
        "entity/project/name",
        "entity/project/name:v0",
        "project/name:v0",
        "name:alias/with/slashes",
    ],
)
def test_artifact_path_roundtrip_from_str(path_str: str):
    """Check that the roundtrip conversion str -> ArtifactPath -> str preserves the original."""
    assert ArtifactPath.from_str(path_str).to_str() == path_str


@pytest.mark.parametrize(
    "path_obj",
    [
        ArtifactPath(prefix=None, project=None, name="name"),
        ArtifactPath(prefix=None, project="project", name="name"),
        ArtifactPath(prefix="entity", project="project", name="name"),
        ArtifactPath(prefix="entity", project="project", name="name:v0"),
        ArtifactPath(prefix=None, project="project", name="name:v0"),
        ArtifactPath(prefix=None, project=None, name="name:alias/with/slashes"),
    ],
)
def test_artifact_path_roundtrip_from_instance(path_obj: ArtifactPath):
    """Check that the roundtrip conversion ArtifactPath -> str -> ArtifactPath preserves the original."""
    assert ArtifactPath.from_str(path_obj.to_str()) == path_obj
