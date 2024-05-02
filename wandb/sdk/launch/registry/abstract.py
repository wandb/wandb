"""Abstract base class for registries."""

from abc import ABC, abstractmethod
from typing import Tuple


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    uri: str

    async def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            (str, str): The username and password.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_repo_uri(self) -> str:
        """Get the URI for a repository.

        Returns:
            str: The URI.
        """
        raise NotImplementedError

    @abstractmethod
    async def check_image_exists(self, image_uri: str) -> bool:
        """Check if an image exists in the registry.

        Arguments:
            image_uri (str): The URI of the image.

        Returns:
            bool: True if the image exists.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_config(
        cls,
        config: dict,
    ) -> "AbstractRegistry":
        """Create a registry from a config."""
        raise NotImplementedError
