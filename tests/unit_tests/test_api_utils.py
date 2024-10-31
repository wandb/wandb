import pytest
from wandb.apis.public.utils import parse_org_from_registry_path


@pytest.mark.parametrize(
    "entity, project, path, expected",
    [
        # Valid cases
        ("org1", "wandb-registry-model", "org1/wandb-registry-model", "org1"),
        ("org1", "wandb-registry-model", "org1/wandb-registry-model/model:v1", "org1"),
        # Invalid cases
        ("", "wandb-registry-model", "org1/wandb-registry-model", ""),  # empty entity
        ("org1", "", "org1/wandb-registry-model", ""),  # empty project
        ("org1", "wandb-registry-model", "", ""),  # empty path
        ("org1", "myproject", "org1/myproject", ""),  # non-registry project
        (
            "org1",
            "wandb-registry-model",
            "other/wandb-registry-model",
            "",
        ),  # mismatched entity
        ("org1", "wandb-registry-model", "org1/other", ""),  # mismatched project
        ("org1", "wandb-registry-model", "org1", ""),  # path is just entity
        (
            "org1",
            "wandb-registry-model",
            "wandb-registry-model",
            "",
        ),  # path is just project
    ],
)
def test_parse_org_from_registry_path(entity, project, path, expected):
    """Test parse_org_from_registry_path with various input combinations."""
    result = parse_org_from_registry_path(entity, project, path)
    assert result == expected
