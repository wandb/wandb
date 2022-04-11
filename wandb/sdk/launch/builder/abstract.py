from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .._project_spec import EntryPoint, LaunchProject


class AbstractBuilder(ABC):
    """Abstract plugin class defining the interface needed to build container images for W&B Launch."""

    type: str

    def __init__(self, builder_config: Dict[str, Any]) -> None:
        self.builder_config = builder_config

    @abstractmethod
    def build_image(
        self,
        launch_project: LaunchProject,
        registry: Optional[str],
        entrypoint: Optional[EntryPoint],
        docker_args: Dict[str, Any],
        runner_type: str,
    ) -> str:
        """Build the image for the given project.

        Args:
            launch_project: The project to build.
            build_ctx_path: The path to the build context.

        Returns:
            The image name.
        """
        pass

    # @abstractmethod
    # def check_image_exists(self, image_name: str, registry: str):
    #     """Check if the image exists.

    #     Args:
    #         image_name: The image name.
    #         registry: The registry to check.

    #     Returns:
    #         True if the image exists.
    #     """
    #     pass

    # @abstractmethod
    # def push_image_to_registry(self, image_name: str, registry: str, tag: str) -> None:
    #     """Push the image to the registry.

    #     Args:
    #         image_name: The image name.
    #         registry: The registry to push to.
    #         tag: The tag to push.
    #     """
    #     pass
