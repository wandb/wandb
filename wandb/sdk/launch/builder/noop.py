"""NoOp builder implementation."""
from typing import Any, Dict

from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.utils import LaunchError

from .._project_spec import EntryPoint, LaunchProject


class NoOpBuilder(AbstractBuilder):
    """NoOp builder."""

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
        cls,
        config: dict,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify: bool = True,
    ) -> "AbstractBuilder":
        """Create a noop builder from a config."""
        return cls(config, environment, registry)

    def verify(self) -> None:
        """Verify the builder."""
        raise LaunchError("Attempted to verify noop builder.")

    def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
    ) -> str:
        """Build the image.

        For this we raise a launch error since it can't build.
        """
        raise LaunchError(
            "Attempted build with noop builder. Specify a builder in your launch config at ~/.config/wandb/launch-config.yaml"
        )
