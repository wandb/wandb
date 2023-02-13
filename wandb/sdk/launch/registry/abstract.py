"""Abstract base class for registries."""
from abc import ABC, abstractmethod


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    @abstractmethod
    def verify(self) -> None:
        """Verify that the registry is configured correctly."""
        raise NotImplementedError

    @abstractmethod
    def get_repo_uri(self) -> str:
        """Get the uri of the given repository."""
        raise NotImplementedError
