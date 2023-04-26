from unittest.mock import MagicMock

from wandb.sdk.launch.registry.google_artifact_registry import GoogleArtifactRegistry


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
