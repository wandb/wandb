from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.registry.google_artifact_registry import GoogleArtifactRegistry
from wandb.sdk.launch.utils import LaunchError


def test_init():
    """Test the initialization of the GoogleArtifactRegistry class."""
    registry = GoogleArtifactRegistry(
        repository="test-repository",
        image_name="test-image",
        environment=MagicMock(),
        verify=False,
    )
    assert registry.repository == "test-repository"
    assert registry.image_name == "test-image"
    assert registry.environment


def test_bad_image_name():
    """Test that a bad image name raises an error."""
    bad_names = [
        "-bad-image-name",
        "bad-image-name!",
        "bad image name",
    ]
    for bad_name in bad_names:
        with pytest.raises(LaunchError) as e:
            GoogleArtifactRegistry(
                repository="test-repository",
                image_name=bad_name,
                environment=MagicMock(),
                verify=False,
            )
        assert f"The image name {bad_name} is invalid." in str(e.value)
