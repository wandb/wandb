"""Implementation of AzureEnvironment class."""

from typing import Tuple

from azure.core.exceptions import HttpResponseError  # type: ignore
from azure.identity import DefaultAzureCredential  # type: ignore
from azure.storage.blob import BlobClient, BlobServiceClient  # type: ignore

from ..errors import LaunchError
from ..utils import AZURE_BLOB_REGEX
from .abstract import AbstractEnvironment


class AzureEnvironment(AbstractEnvironment):
    """AzureEnvironment is a helper for accessing Azure resources."""

    def __init__(
        self,
    ) -> None:
        """Initialize an AzureEnvironment."""

    @classmethod
    def from_config(cls, config: dict, verify: bool = True) -> "AzureEnvironment":
        """Create an AzureEnvironment from a config dict."""
        return cls()

    @classmethod
    def get_credentials(cls) -> DefaultAzureCredential:
        """Get Azure credentials."""
        try:
            return DefaultAzureCredential()
        except Exception as e:
            raise LaunchError(
                f"Could not get Azure credentials. Please make sure you have "
                f"configured your Azure CLI correctly.\n{e}"
            ) from e

    async def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to Azure blob storage.

        Arguments:
            source (str): The path to the file to upload.
            destination (str): The destination path in Azure blob storage. Ex:
                https://<storage_account>.blob.core.windows.net/<storage_container>/<path>
        Raise:
            LaunchError: If the file could not be uploaded.
        """
        storage_account, storage_container, path = self.parse_uri(destination)
        _err_prefix = f"Could not upload file {source} to Azure blob {destination}"
        creds = self.get_credentials()
        try:
            client = BlobClient(
                f"https://{storage_account}.blob.core.windows.net",
                storage_container,
                path,
                credential=creds,
            )
            with open(source, "rb") as f:
                client.upload_blob(f, overwrite=True)
        except HttpResponseError as e:
            raise LaunchError(f"{_err_prefix}: {e.message}") from e
        except Exception as e:
            raise LaunchError(f"{_err_prefix}: {e.__class__.__name__}: {e}") from e

    async def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to Azure blob storage."""
        raise NotImplementedError()

    async def verify_storage_uri(self, uri: str) -> None:
        """Verify that the given blob storage prefix exists.

        Args:
            uri (str): The URI to verify.
        """
        creds = self.get_credentials()
        storage_account, storage_container, _ = self.parse_uri(uri)
        try:
            client = BlobServiceClient(
                f"https://{storage_account}.blob.core.windows.net",
                credential=creds,
            )
            client.get_container_client(storage_container)
        except Exception as e:
            raise LaunchError(
                f"Could not verify storage URI {uri} in container {storage_container}."
            ) from e

    async def verify(self) -> None:
        """Verify that the AzureEnvironment is valid."""
        self.get_credentials()

    @staticmethod
    def parse_uri(uri: str) -> Tuple[str, str, str]:
        """Parse an Azure blob storage URI into a storage account and container.

        Args:
            uri (str): The URI to parse.

        Returns:
            Tuple[str, str, prefix]: The storage account, container, and path.
        """
        match = AZURE_BLOB_REGEX.match(uri)
        if match is None:
            raise LaunchError(f"Could not parse Azure blob URI {uri}.")
        return match.group(1), match.group(2), match.group(3)
