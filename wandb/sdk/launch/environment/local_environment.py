"""Dummy local environment implementation. This is the default environment."""

from typing import Any, Dict, Union

from wandb.sdk.launch.errors import LaunchError

from .abstract import AbstractEnvironment


class LocalEnvironment(AbstractEnvironment):
    """Local environment class."""

    def __init__(self) -> None:
        """Initialize a local environment by doing nothing."""

    @classmethod
    def from_config(
        cls, config: Dict[str, Union[Dict[str, Any], str]]
    ) -> "LocalEnvironment":
        """Create a local environment from a config.

        Arguments:
            config (dict): The config. This is ignored.

        Returns:
            LocalEnvironment: The local environment.
        """
        return cls()

    async def verify(self) -> None:
        """Verify that the local environment is configured correctly."""
        raise LaunchError("Attempted to verify LocalEnvironment.")

    async def verify_storage_uri(self, uri: str) -> None:
        """Verify that the storage URI is configured correctly.

        Arguments:
            uri (str): The storage URI. This is ignored.
        """
        raise LaunchError("Attempted to verify storage uri for LocalEnvironment.")

    async def upload_file(self, source: str, destination: str) -> None:
        """Upload a file from the local filesystem to storage in the environment.

        Arguments:
            source (str): The source file. This is ignored.
            destination (str): The destination file. This is ignored.
        """
        raise LaunchError("Attempted to upload file for LocalEnvironment.")

    async def upload_dir(self, source: str, destination: str) -> None:
        """Upload the contents of a directory from the local filesystem to the environment.

        Arguments:
            source (str): The source directory. This is ignored.
            destination (str): The destination directory. This is ignored.
        """
        raise LaunchError("Attempted to upload directory for LocalEnvironment.")

    async def get_project(self) -> str:
        """Get the project of the local environment.

        Returns: An empty string.
        """
        raise LaunchError("Attempted to get project for LocalEnvironment.")
