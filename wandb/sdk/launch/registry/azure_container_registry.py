"""Implementation of AzureContainerRegistry class."""

from typing import Tuple

from wandb.sdk.launch.utils import LaunchError

from ..environment.azure_environment import AzureEnvironment
from .abstract import AbstractRegistry


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
        cls, config: dict, environment: AzureEnvironment, verify: bool = True
    ) -> "AzureContainerRegistry":
        """Create an AzureContainerRegistry from a config dict."""
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
        return False

    def get_repo_uri(self) -> str:
        return super().get_repo_uri()

    def verify(self) -> None:
        try:
            pass
        except Exception as e:
            raise LaunchError(f"Unable to verify Azure Container Registry: {e}") from e
