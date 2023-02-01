from abc import ABC


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    def verify(self) -> None:
        """Verify that the registry is configured correctly."""
        raise NotImplementedError
