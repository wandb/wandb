from typing import Any, Dict, Optional

from wandb.errors import LaunchError
from wandb.sdk.launch.builder.abstract import AbstractBuilder

from .._project_spec import EntryPoint, LaunchProject


class NoOpBuilder(AbstractBuilder):

    type = "noop"

    def __init__(self, builder_config: Dict[str, Any]) -> None:
        self.builder_config = builder_config

    def build_image(
        self,
        launch_project: LaunchProject,
        registry: Optional[str],
        entrypoint: EntryPoint,
        docker_args: Dict[str, Any],
    ) -> str:
        """Build the image for the given project.

        Args:
            launch_project: The project to build.
            build_ctx_path: The path to the build context.

        Returns:
            The image name.
        """
        raise LaunchError(
            "Attempted build with noop builder. Specify a builder in your launch config at ~/.config/wandb/launch-config.yaml"
        )
