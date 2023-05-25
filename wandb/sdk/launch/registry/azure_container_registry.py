"""Implementation of AzureContainerRegistry class."""

from typing import Tuple
from ..environment.azure_environment import AzureEnvironment
from .abstract import AbstractRegistry

from wandb.sdk.launch.utils import LaunchError


class AzureContainerRegistry(AbstractRegistry):
    """Helper for accessing Azure Container Registry resources."""

    def __init__(
        self,
        environment: AzureEnvironment,
        resource_group: str,
        registry_name: str,
        verify: bool = True,
    ):
        """Initialize an AzureContainerRegistry."""
        self.environment = environment
        self.resource_group = resource_group
        self.registry_name = registry_name
        if verify:
            self.verify()

    @classmethod
    def from_config(
        cls, config: dict, environment: AzureEnvironment, verify: bool = True
    ) -> "AzureContainerRegistry":
        """Create an AzureContainerRegistry from a config dict."""
        resource_group = config.get("resource-group")
        if not resource_group:
            raise LaunchError(
                "You must specify registry.resource-group in order to use acr."
            )
        registry_name = config.get("registry-name")
        if not registry_name:
            raise LaunchError(
                "You must specify registry.registry-name in order to use acr."
            )
        return cls(
            resource_group=resource_group,
            registry_name=registry_name,
            environment=environment,
            verify=verify,
        )

    def get_username_password(self) -> Tuple[str, str]:
        """Get username and password for container registry."""
        return "username", "password"

    def get_client(self):
        """Get a client for the container registry."""
        creds = self.environment.get_credentials()
        creds.get_token()
        creds.credentials.
        return ContainerRegistryManagementClient(
            creds, self.environment.subscription_id
        )

    def check_image_exists(self, image_uri: str) -> bool:
        return super().check_image_exists(image_uri)

    def get_repo_uri(self) -> str:
        return super().get_repo_uri()

    def verify(self) -> None:
        client = self.get_client()
        try:
        
        except Exception as e:
            raise LaunchError(f"Unable to verify Azure Container Registry: {e}") from e
