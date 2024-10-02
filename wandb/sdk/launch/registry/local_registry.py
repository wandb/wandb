"""Local registry implementation."""

import logging
from typing import Tuple

from wandb.docker import is_docker_installed
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import docker_image_exists

from .abstract import AbstractRegistry

_logger = logging.getLogger(__name__)


class LocalRegistry(AbstractRegistry):
    """A local registry.

    This is a dummy registry that is used when no registry is configured.
    """

    def __init__(self) -> None:
        """Initialize a local registry."""
        pass

    @classmethod
    def from_config(
        cls,
        config: dict,
    ) -> "LocalRegistry":
        """Create a local registry from a config.

        Arguments:
            config (dict): The config. This is ignored.
            environment (AbstractEnvironment): The environment. This is ignored.

        Returns:
            LocalRegistry: The local registry.
        """
        return cls()

    async def verify(self) -> None:
        """Verify the local registry by doing nothing."""
        pass

    async def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password of the local registry."""
        raise LaunchError("Attempted to get username and password for LocalRegistry.")

    async def get_repo_uri(self) -> str:
        """Get the uri of the local registry.

        Returns: An empty string.
        """
        return ""

    async def check_image_exists(self, image_uri: str) -> bool:
        """Check if an image exists in the local registry.

        Arguments:
            image_uri (str): The uri of the image.

        Returns:
            bool: True.
        """
        if is_docker_installed():
            return docker_image_exists(image_uri)
        return False
