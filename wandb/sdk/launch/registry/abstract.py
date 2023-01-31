from abc import ABC


class AbstractRegistry(ABC):
    """Abstract base class for registries."""

    def verify(self):
        """Verify that the registry is configured correctly."""
        raise NotImplementedError
