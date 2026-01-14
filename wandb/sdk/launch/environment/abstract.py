"""Abstract base class for environments."""

from abc import ABC, abstractmethod


class AbstractEnvironment(ABC):
    """Abstract base class for environments."""

    region: str

    @abstractmethod
    async def verify(self) -> None:
        """Verify that the environment is configured correctly."""
        raise NotImplementedError

    @abstractmethod
    async def upload_file(self, source: str, destination: str) -> None:
        """Upload a file from the local filesystem to storage in the environment."""
        raise NotImplementedError

    @abstractmethod
    async def upload_dir(self, source: str, destination: str) -> None:
        """Upload the contents of a directory from the local filesystem to the environment."""
        raise NotImplementedError

    @abstractmethod
    async def verify_storage_uri(self, uri: str) -> None:
        """Verify that the storage URI is configured correctly."""
        raise NotImplementedError
