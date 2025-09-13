from pytest import mark, raises
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    RESERVED_ARTIFACT_TYPE_PREFIX,
    ArtifactPath,
    validate_artifact_type,
    validate_project_name,
)


@mark.parametrize(
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
    with raises(ValueError, match=expected_output):
        validate_project_name(project_name)


@mark.parametrize(
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


@mark.parametrize(
    "artifact_type, name",
    [
        (RESERVED_ARTIFACT_TYPE_PREFIX + "invalid", "name"),
        ("job", "name"),
        ("run_table", "run-name"),
        ("code", "source-name"),
    ],
)
def test_validate_artifact_type_invalid(artifact_type, name):
    with raises(ValueError, match="is reserved for internal use"):
        validate_artifact_type(artifact_type, name)


@mark.parametrize(
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


def test_artifact_path_from_str():
    entity, project, name = "entity", "project", "name"

    path_from_name = ArtifactPath.from_str(name)
    assert path_from_name.name == name
    assert path_from_name.project is None
    assert path_from_name.prefix is None

    path_from_project_name = ArtifactPath.from_str(f"{project}/{name}")
    assert path_from_project_name.name == name
    assert path_from_project_name.project == project
    assert path_from_project_name.prefix is None

    path_from_entity_project_name = ArtifactPath.from_str(f"{entity}/{project}/{name}")
    assert path_from_entity_project_name.name == name
    assert path_from_entity_project_name.project == project
    assert path_from_entity_project_name.prefix == entity


@mark.parametrize(
    "path",
    [
        "name",
        "project/name",
        "entity/project/name",
    ],
)
def test_artifact_path_roundtrip_str(path: str):
    assert ArtifactPath.from_str(path).to_str() == path
