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
        pass
