from abc import ABC


class AbstractEnvironment(ABC):
    """Abstract base class for environments."""

    def verify(self) -> None:
        """Verify that the environment is configured correctly."""
        raise NotImplementedError
