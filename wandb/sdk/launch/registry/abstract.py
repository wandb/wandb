"""Abstract base class for registries."""
from abc import ABC, abstractmethod


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    @abstractmethod
    def verify(self) -> None:
        """Verify that the registry is configured correctly."""
        raise NotImplementedError
