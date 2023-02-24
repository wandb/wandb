"""Abstract base class for registries."""
from abc import ABC, abstractmethod
from typing import Tuple


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

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
