from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.errors import LaunchError


def test_azure_environment_from_config(mocker):
    """Test AzureEnvironment class."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {
        "environment": {
            "type": "azure",
        }
    }
    AzureEnvironment.from_config(config)


@pytest.mark.asyncio
async def test_azure_upload_file(mocker, runner):
    """Test AzureEnvironment class."""
    credentials = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        credentials,
    )
    config = {
        "environment": {
            "type": "azure",
        }
    }
    blob_client = MagicMock()
    blob_client.upload_blob = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.BlobClient",
        return_value=blob_client,
    )
    azure = AzureEnvironment.from_config(config)
    with runner.isolated_filesystem():
        open("source", "w").write("test")
        destination = (
            "https://storage_account.blob.core.windows.net/storage_container/path"
        )
        await azure.upload_file("source", destination)
        blob_client.upload_blob.assert_called_once()

        blob_client.upload_blob.side_effect = Exception("test")
        with pytest.raises(LaunchError):
            await azure.upload_file("source", destination)


@pytest.mark.parametrize(
    "uri,expected",
    [
        (
            "https://storage_account.blob.core.windows.net/storage_container/path",
            ("storage_account", "storage_container", "path"),
        ),
        (
            "https://storage_account.blob.core.windows.net/storage_container/path/",
            ("storage_account", "storage_container", "path/"),
        ),
        (
            "https://storage_account.blob.core.windows.net/storage_container/path/file",
            ("storage_account", "storage_container", "path/file"),
        ),
        (
            "https://storage_account.blob.core.windows.net/storage_container/path/file/",
            ("storage_account", "storage_container", "path/file/"),
        ),
    ],
)
def test_parse_uri(uri, expected):
    """Test AzureEnvironment class parse_uri method."""
    azure = AzureEnvironment()
    assert azure.parse_uri(uri) == expected


@pytest.mark.asyncio
async def test_azure_verify_storage_uri(mocker):
    """Check that we properly verify storage URIs."""
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.DefaultAzureCredential",
        MagicMock(),
    )
    config = {
        "environment": {
            "type": "azure",
        }
    }
    blob_service_client = MagicMock()
    blob_service_client.get_container_client = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.environment.azure_environment.BlobServiceClient",
        return_value=blob_service_client,
    )
    azure = AzureEnvironment.from_config(config)
    await azure.verify_storage_uri(
        "https://storage_account.blob.core.windows.net/storage_container/path"
    )
    blob_service_client.get_container_client.assert_called_once()
