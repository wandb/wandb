"""Abstract base class for registries."""
from abc import ABC, abstractmethod
from typing import Tuple

from ..environment.abstract import AbstractEnvironment


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    uri: str

    @abstractmethod
    def verify(self) -> None:
        """Verify that the registry is configured correctly."""
        raise NotImplementedError

    @abstractmethod
    def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            (str, str): The username and password.
        """
        raise NotImplementedError

    @abstractmethod
    def get_repo_uri(self) -> str:
        """Get the URI for a repository.

        Returns:
            str: The URI.
        """
        raise NotImplementedError

    @abstractmethod
    def check_image_exists(self, image_uri: str) -> bool:
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
        cls, config: dict, environment: "AbstractEnvironment", verify: bool = True
    ) -> "AbstractRegistry":
        """Create a registry from a config."""
        raise NotImplementedError
