from abc import ABC, abstractmethod
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Union

from dockerpycreds.utils import find_executable  # type: ignore
import wandb
from wandb import Settings
from wandb.apis.internal import Api
from wandb.errors import CommError

from .._project_spec import EntryPoint, LaunchProject

_logger = logging.getLogger(__name__)


class AbstractBuilder(ABC):
    """Abstract plugin class defining the interface needed to build container images for W&B Launch."""

    type: str

    def __init__(self, builder_config: Dict[str, Any]) -> None:
        self.builder_config = builder_config

    @abstractmethod
    def build_image(
        self,
        api: Api,
        launch_project: LaunchProject,
        registry: Optional[str],
        entrypoint: EntryPoint,
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

    @abstractmethod
    def check_image_exists(self, image_name: str, registry: str):
        """Check if the image exists.

        Args:
            image_name: The image name.
            registry: The registry to check.

        Returns:
            True if the image exists.
        """
        pass

    @abstractmethod
    def push_image_to_registry(self, image_name: str, registry: str, tag: str) -> None:
        """Push the image to the registry.

        Args:
            image_name: The image name.
            registry: The registry to push to.
            tag: The tag to push.
        """
        pass
