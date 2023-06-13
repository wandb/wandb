"""Implementation of AzureContainerRegistry class."""
import re
from typing import TYPE_CHECKING, Tuple

from wandb.util import get_module

from ..environment.abstract import AbstractEnvironment
from ..environment.azure_environment import AzureEnvironment
from ..errors import LaunchError
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
        environment: AzureEnvironment,
        uri: str,
        verify: bool = True,
    ):
        """Initialize an AzureContainerRegistry."""
        self.environment = environment
        self.uri = uri
        if verify:
            self.verify()

    @classmethod
    def from_config(
        cls, config: dict, environment: AbstractEnvironment, verify: bool = True
    ) -> "AzureContainerRegistry":
        """Create an AzureContainerRegistry from a config dict."""
        if not isinstance(environment, AzureEnvironment):
            raise LaunchError(
                "AzureContainerRegistry requires an AzureEnvironment to be passed in."
            )
        uri = config.get("uri")
        if uri is None:
            raise LaunchError(
                "Please specify a registry name to use under the registry.uri."
            )
        return cls(
            uri=uri,
            environment=environment,
            verify=verify,
        )

    def get_username_password(self) -> Tuple[str, str]:
        """Get username and password for container registry."""
        raise NotImplementedError

    def check_image_exists(self, image_uri: str) -> bool:
        """Check if image exists in container registry.

        WARNING: This is not implemented for Azure Container Registry and will
        always return False.

        Args:
            image_uri (str): Image URI to check.

        Returns:
            bool: False
        """
        credential = self.environment.get_credentials()
        client = ContainerRegistryClient(self.uri, credential)
        repository, tag = image_uri.split(":")
        try:
            client.get_manifest_properties(repository, tag)
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            raise LaunchError(
                f"Unable to check if image exists in Azure Container Registry: {e}"
            ) from e

    def get_repo_uri(self) -> str:
        return self.uri

    def verify(self) -> None:
        try:
            _ = self.registry_name
        except Exception as e:
            raise LaunchError(f"Unable to verify Azure Container Registry: {e}") from e

    @property
    def registry_name(self) -> str:
        regex = r"https://([\w]+).azurecr.io/?"
        match = re.match(regex, self.uri)
        if match is None:
            raise LaunchError(
                f"Unable to parse Azure Container Registry URI: {self.uri}"
            )
        return match.group(1)
