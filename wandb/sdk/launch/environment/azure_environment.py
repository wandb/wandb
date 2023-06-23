"""Implementation of AzureEnvironment class."""

import re
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from azure.identity import DefaultAzureCredential  # type: ignore
    from azure.storage.blob import BlobClient, BlobServiceClient  # type: ignore

from wandb.util import get_module

from ..errors import LaunchError
from .abstract import AbstractEnvironment

AZURE_BLOB_REGEX = re.compile(
    r"^https://([^\.]+)\.blob\.core\.windows\.net/([^/]+)/?(.*)$"
)


DefaultAzureCredential = get_module(  # noqa: F811
    "azure.identity",
    required="The azure-identity package is required to use launch with Azure. Please install it with `pip install azure-identity`.",
).DefaultAzureCredential
blob = get_module(
    "azure.storage.blob",
    required="The azure-storage-blob package is required to use launch with Azure. Please install it with `pip install azure-storage-blob`.",
)
BlobClient, BlobServiceClient = blob.BlobClient, blob.BlobServiceClient  # noqa: F811


class AzureEnvironment(AbstractEnvironment):
    """AzureEnvironment is a helper for accessing Azure resources."""

    def __init__(
        self,
        verify: bool = True,
    ):
        """Initialize an AzureEnvironment."""
        if verify:
            self.verify()

    @classmethod
    def from_config(cls, config: dict, verify: bool = True) -> "AzureEnvironment":
        """Create an AzureEnvironment from a config dict."""
        return cls(verify=verify)

    @classmethod
    def get_credentials(cls) -> DefaultAzureCredential:
        """Get Azure credentials."""
        try:
            return DefaultAzureCredential()
        except Exception as e:
            raise LaunchError(
                "Could not get Azure credentials. Please make sure you have "
                "configured your Azure CLI correctly."
            ) from e

    def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to Azure blob storage.

        Arguments:
            source (str): The path to the file to upload.
            destination (str): The destination path in Azure blob storage. Ex:
                https://<storage_account>.blob.core.windows.net/<storage_container>/<path>
        Raise:
            LaunchError: If the file could not be uploaded.
        """
        storage_account, storage_container, path = self.parse_uri(destination)
        creds = self.get_credentials()
        try:
            client = BlobClient(
                f"https://{storage_account}.blob.core.windows.net",
                storage_container,
                path,
                credential=creds,
            )
            with open(source, "rb") as f:
                client.upload_blob(f)
        except Exception as e:
            raise LaunchError(
                f"Could not upload file {source} to Azure blob {destination}."
            ) from e

    def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to Azure blob storage."""
        raise NotImplementedError()

    def verify_storage_uri(self, uri: str) -> None:
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

    def verify(self) -> None:
        """Verify that the AzureEnvironment is valid."""
        self.get_credentials()

    @staticmethod
    def parse_uri(uri: str) -> Tuple[str, str, str]:
        """Parse an Azure blob storage URI into a storage account and container.

        Args:
            uri (str): The URI to parse.

        Returns:
            Tuple[str, str]: The storage account and container.
        """
        match = AZURE_BLOB_REGEX.match(uri)
        if match is None:
            raise LaunchError(f"Could not parse Azure blob URI {uri}.")
        return match.group(1), match.group(2), match.group(3)
