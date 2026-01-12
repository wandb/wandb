from __future__ import annotations

from unittest.mock import MagicMock

import google.api_core.exceptions
import pytest
from wandb.sdk.launch.registry.google_artifact_registry import GoogleArtifactRegistry
from wandb.sdk.launch.utils import LaunchError


@pytest.fixture
def mock_gcp_default_credentials(monkeypatch):
    """Mock the default credentials for GCP."""
    credentials = MagicMock()
    monkeypatch.setattr(
        "google.auth.default",
        lambda *args, **kwargs: (credentials, "us-central1"),
    )
    return credentials


@pytest.fixture
def mock_gcp_artifact_registry_client(monkeypatch):
    """Mock the Google Artifact Registry client."""
    client = MagicMock()
    monkeypatch.setattr(
        "google.cloud.artifactregistry.ArtifactRegistryClient",
        lambda *args, **kwargs: client,
    )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uri, repository, image_name, project, region, expected",
    [
        # Fails because nothing is provided.
        (None, None, None, None, None, None),
        # Work because URI is provided.
        (
            "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
            None,
            None,
            None,
            None,
            "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
        ),
        # Works because uri components are provided.
        (
            None,
            "vertex-ai",
            "wandb-ml",
            "wandb-ml",
            "us-central1",
            "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
        ),
        # Fails because no region.
        (
            None,
            "vertex-ai",
            "wandb-ml",
            "wandb-ml",
            None,
            None,
        ),
        # Fails because no image-name.
        (
            None,
            "vertex-ai",
            None,
            "wandb-ml",
            "us-central1",
            None,
        ),
    ],
)
async def test_google_artifact_registry_helper_constructor(
    uri, repository, image_name, project, region, expected, mock_gcp_default_credentials
):
    """Test that the GoogleArtifactRegistry constructor works as expected.

    This test is parameterized by the following variables:

    uri: str
    repository: str
    image_name: str
    project: str
    region: str
    expected: str

    The test will fail if expected is None and the constructor does not raise a LaunchError.
    Otherwise, the test will use the first 5 variables as kwargs for the constructor and
    assert that the uri attribute of the helper is equal to expected.
    """
    if expected is None:
        with pytest.raises(LaunchError):
            GoogleArtifactRegistry(
                uri=uri,
                repository=repository,
                image_name=image_name,
                project=project,
                region=region,
            )
    else:
        helper = GoogleArtifactRegistry(
            uri=uri,
            repository=repository,
            image_name=image_name,
            project=project,
            region=region,
        )
        assert (await helper.get_repo_uri()) == expected


@pytest.mark.asyncio
async def test_get_username_password(mock_gcp_default_credentials):
    """Test that the GoogleArtifactRegistry.get_username_password method works as expected."""
    mock_gcp_default_credentials.token = "token"
    helper = GoogleArtifactRegistry(
        uri="us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
    )
    assert (await helper.get_username_password()) == (
        "oauth2accesstoken",
        "token",
    )


def test_from_config(mock_gcp_default_credentials, mock_gcp_artifact_registry_client):
    """Test that the GoogleArtifactRegistry.from_config method works as expected."""
    config = {
        "uri": "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
    }
    helper = GoogleArtifactRegistry.from_config(config)
    assert helper.uri == "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml"
    assert helper.project == "wandb-ml"
    assert helper.region == "us-central1"
    assert helper.repository == "vertex-ai"
    # Test that we raise a LaunchError if we have unsupported keys.
    config["unsupported"] = "unsupported"
    with pytest.raises(LaunchError):
        GoogleArtifactRegistry.from_config(config)


@pytest.mark.asyncio
async def test_check_image_exists(
    mock_gcp_default_credentials, mock_gcp_artifact_registry_client
):
    """Test that the GoogleArtifactRegistry.check_image_exists method works as expected."""
    mock_gcp_artifact_registry_client.list_docker_images.return_value = [
        MagicMock(tags=["hello", "world", "foo"]),
    ]
    helper = GoogleArtifactRegistry(
        uri="us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml",
    )
    assert await helper.check_image_exists(
        "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml:hello"
    )
    assert await helper.check_image_exists(
        "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml:world"
    )
    assert not await helper.check_image_exists(
        "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml:goodbye"
    )
    # Test that if the repository does not exist, we raise a LaunchError.
    mock_gcp_artifact_registry_client.list_docker_images.side_effect = (
        google.api_core.exceptions.NotFound("Not found")
    )
    with pytest.raises(LaunchError):
        await helper.check_image_exists(
            "us-central1-docker.pkg.dev/wandb-ml/vertex-ai/wandb-ml:hello"
        )
