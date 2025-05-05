import pytest
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX, validate_project_name


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
