"""Implementation of AzureEnvironment class."""

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient

from ..utils import LaunchError
from .abstract import AbstractEnvironment


class AzureEnvironment(AbstractEnvironment):
    """AzureEnvironment is a helper for accessing Azure resources."""

    def __init__(
        self,
        storage_account: str,
        storage_container: str,
        subscription_id: str,
        verify: bool = True,
    ):
        """Initialize an AzureEnvironment."""
        self.storage_account = storage_account
        self.storage_container = storage_container
        self.subscription_id = subscription_id
        if verify:
            self.verify()

    @classmethod
    def from_config(cls, config: dict, verify: bool = True) -> "AzureEnvironment":
        """Create an AzureEnvironment from a config dict."""
        storage_account = config.get("storage-account")
        if storage_account is None:
            raise LaunchError(
                "Please specify a storage account to use under the environment.storage-account key."
            )
        storage_container = config.get("storage-container")
        if storage_container is None:
            raise LaunchError(
                "Please specify a storage container to use under the "
                "environment.storage-container key."
            )
        subscription_id = config.get("subscription-id")
        if subscription_id is None:
            raise LaunchError(
                "Please specify a subscription ID to use under the "
                "environment.subscription-id key."
            )
        return cls(
            storage_account=storage_account,
            storage_container=storage_container,
            subscription_id=subscription_id,
            verify=verify,
        )

    @classmethod
    def get_credentials(cls):
        """Get Azure credentials."""
        return DefaultAzureCredential()

    def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to Azure blob storage."""
        creds = self.get_credentials()
        client = BlobClient(
            f"https://{self.storage_account}.blob.core.windows.net",
            self.storage_container,
            destination,
            credential=creds,
        )
        client.upload_blob(source)

    def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to Azure blob storage."""
        raise NotImplementedError()

    def verify_storage_uri(self, uri: str) -> None:
        """Verify that the given blob storage prefix exists.

        Args:
            uri (str): The URI to verify.
        """
        creds = self.get_credentials()
        client = BlobClient(
            f"https://{self.storage_account}.blob.core.windows.net",
            self.storage_container,
            uri,
            credential=creds,
        )
        client.get_blob_properties()

    def verify(self) -> None:
        """Verify that the AzureEnvironment is valid."""
        creds = self.get_credentials()
        client = BlobClient(
            f"https://{self.storage_account}.blob.core.windows.net",
            self.storage_container,
            "test",
            credential=creds,
        )
        client.upload_blob("test")
        client.delete_blob()
