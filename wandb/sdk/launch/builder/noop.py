"""NoOp builder implementation."""

from typing import Any, Dict, Optional

from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.registry.abstract import AbstractRegistry

from .._project_spec import EntryPoint, LaunchProject
from ..agent.job_status_tracker import JobAndRunStatusTracker


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
        self.environment = environment
        self.registry = registry

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

    async def verify(self) -> None:
        """Verify the builder."""
        raise LaunchError("Attempted to verify noop builder.")

    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> str:
        """Build the image.

        For this we raise a launch error since it can't build.
        """
        raise LaunchError(
            "Attempted build with noop builder. Specify a builder in your launch config at ~/.config/wandb/launch-config.yaml.\n"
            "Note: Jobs sourced from git repos and code artifacts require a builder, while jobs sourced from Docker images do not.\n"
            "See https://docs.wandb.ai/guides/launch/create-job."
        )
