"""Abstract plugin class defining the interface needed to build container images for W&B Launch."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .._project_spec import EntryPoint, LaunchProject

from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.environment.abstract import AbstractEnvironment


class AbstractBuilder(ABC):
    """Abstract plugin class defining the interface needed to build container images for W&B Launch."""

    builder_type: str
    registry: AbstractRegistry
    builder_config: Dict[str, Any]

    @abstractmethod
    def __init__(
        self,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify=True,
    ) -> None:
        """Initialize a builder.

        Args:
            builder_config: The builder config.
            registry: The registry to use.
            verify: Whether to verify the functionality of the builder.

        Raises:
            LaunchError: If the builder cannot be intialized or verified.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_config(
        cls, config: dict, registry: AbstractRegistry, verify: bool = True
    ) -> "AbstractBuilder":
        """Create a builder from a config dictionary.

        Args:
            config: The config dictionary.
            registry: The registry to use.
            verify: Whether to verify the functionality of the builder.

        Returns:
            The builder.
        """
        raise NotImplementedError

    @abstractmethod
    def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
    ) -> str:
        """Build the image for the given project.

        Args:
            launch_project: The project to build.
            build_ctx_path: The path to the build context.

        Returns:
            The image name.
        """
        raise NotImplementedError

    @abstractmethod
    def verify(self) -> None:
        """Verify that the builder can be used to build images.

        Raises:
            LaunchError: If the builder cannot be used to build images.
        """
        raise NotImplementedError
