"""Implementation of AzureContainerRegistry class."""

from ..environment.azure_environment import AzureEnvironment
from .abstract import AbstractRegistry


class AzureContainerRegistry(AbstractRegistry):
    """Helper for accessing Azure Container Registry resources."""

    def __init__(
        self,
        environment: AzureEnvironment,
        verify: bool = True,
    ):
        """Initialize an AzureContainerRegistry."""
        self.environment = environment
        self.verify = verify

    @classmethod
    def from_config(
        cls, config: dict, environment: AzureEnvironment, verify: bool = True
    ) -> "AzureContainerRegistry":
        """Create an AzureContainerRegistry from a config dict."""
        return cls(
            environment=environment,
            verify=verify,
        )
