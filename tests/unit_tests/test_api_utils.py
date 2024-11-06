import pytest
from wandb.apis.public.utils import parse_org_from_registry_path


@pytest.mark.parametrize(
    "path, path_type, expected",
    [
        # Valid cases
        ("my-org/wandb-registry-model", "project", "my-org"),
        ("my-org/wandb-registry-model/model:v1", "artifact", "my-org"),
        # Invalid cases
        ("", "project", ""),  # empty path
        ("", "artifact", ""),  # empty path
        ("my-org/myproject", "project", ""),  # not a Registry project
        ("my-org/myproject/model", "artifact", ""),  # not a Registry project
        # No orgs set in artifact paths
        ("model", "artifact", ""),
        ("wandb-registry-model/model", "artifact", ""),
        # No orgs set in project path
        ("wandb-registry-model", "project", ""),
    ],
)
def test_parse_org_from_registry_path(path, path_type, expected):
    """Test parse_org_from_registry_path with various input combinations."""
    result = parse_org_from_registry_path(path, path_type)
    assert result == expected
