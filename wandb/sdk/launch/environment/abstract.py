from abc import ABC


class AbstractEnvironment(ABC):
    """Abstract base class for environments."""

    def verify(self) -> None:
        """Verify that the environment is configured correctly."""
        raise NotImplementedError

    def upload_file(self, source: str, destination: str) -> None:
        """Upload a file from the local filesystem to storage in the environment."""
        raise NotImplementedError

    def upload_dir(self, source: str, destination: str) -> None:
        """Upload the contents of a directory from the local filesystem to the environment."""
        raise NotImplementedError
