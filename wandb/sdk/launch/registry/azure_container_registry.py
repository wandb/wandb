"""Implementation of AzureContainerRegistry class."""

import re
from typing import TYPE_CHECKING, Optional, Tuple

from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import AZURE_CONTAINER_REGISTRY_URI_REGEX
from wandb.util import get_module

from .abstract import AbstractRegistry

if TYPE_CHECKING:
    from azure.containerregistry import ContainerRegistryClient  # type: ignore
    from azure.core.exceptions import ResourceNotFoundError  # type: ignore


ContainerRegistryClient = get_module(  # noqa: F811
    "azure.containerregistry",
    required="The azure-containerregistry package is required to use launch with Azure. Please install it with `pip install azure-containerregistry`.",
).ContainerRegistryClient

ResourceNotFoundError = get_module(  # noqa: F811
    "azure.core.exceptions",
    required="The azure-core package is required to use launch with Azure. Please install it with `pip install azure-core`.",
).ResourceNotFoundError


class AzureContainerRegistry(AbstractRegistry):
    """Helper for accessing Azure Container Registry resources."""

    def __init__(
        self,
        uri: Optional[str] = None,
        registry_name: Optional[str] = None,
        repo_name: Optional[str] = None,
    ):
        """Initialize an AzureContainerRegistry."""
        if uri is not None:
            self.uri = uri
            if any(x is not None for x in (registry_name, repo_name)):
                raise LaunchError(
                    "Please specify either a registry name and repo name or a registry URI."
                )
            if self.uri.startswith("https://"):
                self.uri = self.uri[len("https://") :]
            match = AZURE_CONTAINER_REGISTRY_URI_REGEX.match(self.uri)
            if match is None:
                raise LaunchError(
                    f"Unable to parse Azure Container Registry URI: {self.uri}"
                )
            self.registry_name = match.group(1)
            self.repo_name = match.group(2)
        else:
            if any(x is None for x in (registry_name, repo_name)):
                raise LaunchError(
                    "Please specify both a registry name and repo name or a registry URI."
                )
            self.registry_name = registry_name
            self.repo_name = repo_name
            self.uri = f"{self.registry_name}.azurecr.io/{self.repo_name}"

    @classmethod
    def from_config(
        cls,
        config: dict,
    ) -> "AzureContainerRegistry":
        """Create an AzureContainerRegistry from a config dict.

        Args:
            config (dict): The config dict.
            environment (AbstractEnvironment): The environment to use.
            verify (bool, optional): Whether to verify the registry. Defaults to True.

        Returns:
            AzureContainerRegistry: The registry.

        Raises:
            LaunchError: If the config is invalid.
        """
        uri = config.get("uri")
        if uri is None:
            raise LaunchError(
                "Please specify a registry name to use under the registry.uri."
            )
        return cls(
            uri=uri,
        )

    async def get_username_password(self) -> Tuple[str, str]:
        """Get username and password for container registry."""
        raise NotImplementedError

    async def check_image_exists(self, image_uri: str) -> bool:
        """Check if image exists in container registry.

        Args:
            image_uri (str): Image URI to check.

        Returns:
            bool: True if image exists, False otherwise.
        """
        match = re.match(AZURE_CONTAINER_REGISTRY_URI_REGEX, image_uri)
        if match is None:
            raise LaunchError(
                f"Unable to parse Azure Container Registry URI: {image_uri}"
            )
        registry = match.group(1)
        repository = match.group(2)
        tag = match.group(3)
        credential = AzureEnvironment.get_credentials()
        client = ContainerRegistryClient(f"https://{registry}.azurecr.io", credential)
        try:
            client.get_manifest_properties(repository, tag)
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            raise LaunchError(
                f"Unable to check if image exists in Azure Container Registry: {e}"
            ) from e

    async def get_repo_uri(self) -> str:
        return f"{self.registry_name}.azurecr.io/{self.repo_name}"
