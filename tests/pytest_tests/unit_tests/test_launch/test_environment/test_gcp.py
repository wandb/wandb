from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from wandb.errors import LaunchError
from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment


def test_environment_verify(mocker):
    """Test that the environment is verified correctly."""
    credentials = MagicMock()
    credentials.refresh = MagicMock()
    credentials.valid = True
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.auth.default",
        return_value=(credentials, "project"),
    )
    mock_region_client = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.cloud.compute_v1.RegionsClient",
        mock_region_client,
    )
    GcpEnvironment("region")
    mock_region_client.assert_called_once_with(credentials=credentials)
    mock_region_client.return_value.get.assert_called_once_with(
        project="project", region="region"
    )


def test_environment_no_default_creds(mocker):
    """Test that the environment raises an error if there are no default credentials."""
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.auth.default",
        side_effect=DefaultCredentialsError,
    )
    with pytest.raises(LaunchError):
        GcpEnvironment("region")


def test_environment_verify_invalid_creds(mocker):
    """Test that the environment raises an error if the credentials are invalid."""
    credentials = MagicMock()
    credentials.refresh = MagicMock()
    credentials.valid = False
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.auth.default",
        return_value=(credentials, "project"),
    )
    with pytest.raises(LaunchError):
        GcpEnvironment("region")
    credentials.refresh = MagicMock(side_effect=RefreshError("error"))
    with pytest.raises(LaunchError):
        GcpEnvironment("region")


def test_upload_file(mocker):
    credentials = MagicMock()
    credentials.valid = True
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.auth.default",
        return_value=(credentials, "project"),
    )
    mock_storage_client = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.google.cloud.storage.Client",
        mock_storage_client,
    )
    mock_bucket = MagicMock()
    mock_storage_client.return_value.bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    environment = GcpEnvironment("region", verify=False)
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.os.path.isfile",
        return_value=True,
    )
    environment.upload_file("source", "gs://bucket/key")
    mock_storage_client.assert_called_once_with(credentials=credentials)
    mock_storage_client.return_value.bucket.assert_called_once_with("bucket")
    mock_bucket.blob.assert_called_once_with("key")
    mock_blob.upload_from_filename.assert_called_once_with("source")
