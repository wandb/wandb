import pytest
from hypothesis import example, given
from hypothesis.strategies import from_regex, just, one_of, tuples
from wandb.sdk.artifacts._validators import (
    REGISTRY_PREFIX,
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


# Original test cases
@example(type_and_name=("job", "name"))
@example(type_and_name=("run_table", "run-name"))
@example(type_and_name=("code", "source-name"))
@example(type_and_name=("wandb-invalid", "name"))
@given(
    type_and_name=one_of(
        # "wandb-*" artifact types are ALWAYS reserved
        tuples(
            from_regex(r"^wandb-[$a-zA-Z0-9_\-.]*$"),
            from_regex(r"^[a-zA-Z0-9_\-.]*$"),
        ),
        # "job" artifact type is ALWAYS reserved
        tuples(just("job"), from_regex(r"^[a-zA-Z0-9_\-.]*$")),
        # "run_table" artifact type is reserved for artifacts named: "run-*"
        tuples(just("run_table"), from_regex(r"^run-[a-zA-Z0-9_\-.]*$")),
        # "code" artifact type is reserved for artifacts named: "source-*"
        tuples(just("code"), from_regex(r"^source-[a-zA-Z0-9_\-.]*$")),
    )
)
def test_validate_artifact_type_invalid(type_and_name: tuple[str, str]):
    typ, name = type_and_name
    with pytest.raises(ValueError, match="is reserved for internal use"):
        validate_artifact_type(typ, name)


@pytest.mark.parametrize(
    "type_and_name",
    [
        ("dataset", "name"),
        ("wandbtype", "name"),
        ("code", "name"),
        ("run_table", "name"),
    ],
)
def test_validate_artifact_type_valid(type_and_name: tuple[str, str]):
    typ, name = type_and_name
    assert validate_artifact_type(typ, name) == typ
