from typing import Any, Dict, Optional

from wandb.errors import LaunchError
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.environment.abstract import AbstractEnvironment

from .._project_spec import EntryPoint, LaunchProject


class NoOpBuilder(AbstractBuilder):
    type = "noop"

    def __init__(
        self,
        builder_config: Dict[str, Any],
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
    ) -> None:
        """Initialize a NoOpBuilder."""
        pass

    @classmethod
    def from_config(
        cls, config: dict, registry: AbstractRegistry, verify: bool = True
    ) -> "AbstractBuilder":
        """Create a noop builder from a config."""
        return cls(config, None, None)

    def verify(self) -> None:
        """Verify the builder."""
        raise LaunchError("Attempted to verify noop builder.")

    def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
    ) -> str:
        """Build the image.

        For this class we just return the image name.
        """
        raise LaunchError(
            "Attempted build with noop builder. Specify a builder in your launch config at ~/.config/wandb/launch-config.yaml"
        )
