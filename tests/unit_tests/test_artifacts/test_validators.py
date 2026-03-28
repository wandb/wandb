from pathlib import Path, PurePosixPath, PureWindowsPath

from pytest import mark, raises
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
    RESERVED_ARTIFACT_TYPE_PREFIX,
    ArtifactPath,
    validate_artifact_path,
    validate_artifact_type,
    validate_project_name,
)
from wandb.sdk.lib.paths import StrPath


@mark.parametrize(
    "project_name, expected",
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
def test_validate_project_name_invalid(project_name, expected):
    with raises(ValueError, match=expected):
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
    assert validate_project_name(project_name) == project_name


@mark.parametrize(
    "artifact_type, name",
    [
        (f"{RESERVED_ARTIFACT_TYPE_PREFIX}invalid", "name"),
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


@mark.parametrize(
    ("path", "expected"),
    [
        ("file.txt", "file.txt"),
        (Path("file.txt"), "file.txt"),
        (PurePosixPath("file.txt"), "file.txt"),
        (PureWindowsPath("file.txt"), "file.txt"),
        ("nested/file.txt", "nested/file.txt"),
        (Path("nested/file.txt"), "nested/file.txt"),
        (PurePosixPath("nested/file.txt"), "nested/file.txt"),
        (PureWindowsPath(r"nested\file.txt"), "nested/file.txt"),
    ],
)
def test_validate_artifact_path_valid(path: StrPath, expected: str):
    assert validate_artifact_path(path) == expected


@mark.parametrize(
    "path",
    [
        "",
        ".",
        "../file.txt",
        "nested/../file.txt",
        "//server/share/file.txt",
        "/file.txt",
        "//file.txt",
        "///file.txt",
        "////file.txt",
        r"\file.txt",
        r"C:\file.txt",
        r"C:file.txt",
        PurePosixPath("/file.txt"),
        PureWindowsPath(r"..\file.txt"),
        PureWindowsPath(r"\file.txt"),
        PureWindowsPath(r"C:\file.txt"),
        PureWindowsPath(r"C:file.txt"),
    ],
)
def test_validate_artifact_path_invalid(path):
    with raises(ValueError, match="Invalid artifact path"):
        validate_artifact_path(path)


@mark.parametrize(
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
    with raises(ValueError):
        ArtifactPath.from_str("path/with/too/many/parts")


@mark.parametrize(
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


@mark.parametrize(
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
