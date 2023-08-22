import os
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from wandb.sdk.launch.environment.gcp_environment import (
    GcpEnvironment,
    get_gcloud_config_value,
    GCP_REGION_ENV_VAR,
)
from wandb.sdk.launch.errors import LaunchError


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
    mock_storage_client.return_value.bucket.assert_called_once_with("bucket")
    mock_bucket.blob.assert_called_once_with("key")
    mock_blob.upload_from_filename.assert_called_once_with("source")


def test_upload_dir(mocker):
    """Test that a directory is uploaded correctly."""
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
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.os.path.isdir",
        return_value=True,
    )
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.os.walk",
        return_value=[
            ("source", ["subdir"], ["file1", "file2"]),
            (os.path.join("source", "subdir"), [], ["file3"]),
        ],
    )
    environment.upload_dir("source", "gs://bucket/key")
    mock_storage_client.return_value.bucket.assert_called_once_with("bucket")

    def _relpath(path, start):
        return path.replace(start, "").lstrip("/")

    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.os.path.relpath",
        _relpath,
    )

    mock_bucket.blob.assert_has_calls(
        [
            mocker.call("key/file1"),
            mocker.call().upload_from_filename(os.path.join("source", "file1")),
            mocker.call("key/file2"),
            mocker.call().upload_from_filename(os.path.join("source", "file2")),
            mocker.call("key/subdir/file3"),
            mocker.call().upload_from_filename(
                os.path.join("source", "subdir", "file3")
            ),
        ],
    )


@pytest.mark.parametrize(
    "region,value",
    [
        (b"us-central1", "us-central1"),
        (b"unset", None),
    ],
)
def test_get_gcloud_config_value(mocker, region, value):
    """Test that we correctly handle gcloud outputs."""
    # Mock subprocess.check_output
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.subprocess.check_output",
        return_value=region,
    )
    # environment = GcpEnvironment.from_default()
    assert get_gcloud_config_value("region") == value


def test_from_default_gcloud(mocker):
    """Test constructing gcp environment in a region read by the gcloud CLI."""
    #  First test that we construct from gcloud output
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.subprocess.check_output",
        return_value=b"us-central1",
    )
    environment = GcpEnvironment.from_default(verify=False)
    assert environment.region == "us-central1"


def test_from_default_env(mocker):
    """Test that we can construct default reading region from env var."""
    # Patch gcloud output
    mocker.patch(
        "wandb.sdk.launch.environment.gcp_environment.subprocess.check_output",
        return_value=b"unset",
    )
    # Patch env vars
    mocker.patch.dict(
        os.environ,
        {
            GCP_REGION_ENV_VAR: "us-central1",
        },
    )
    environment = GcpEnvironment.from_default(verify=False)
    assert environment.region == "us-central1"
