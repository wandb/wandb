"""Implementation of the docker builder."""

import logging
import os
from typing import Any, Dict, Optional

import wandb
import wandb.docker as docker
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder, registry_from_uri
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry

from .._project_spec import EntryPoint, LaunchProject
from ..errors import LaunchDockerError, LaunchError
from ..registry.anon import AnonynmousRegistry
from ..registry.local_registry import LocalRegistry
from ..utils import (
    LOG_PREFIX,
    event_loop_thread_exec,
    warn_failed_packages_from_build_logs,
)
from .build import _WANDB_DOCKERFILE_NAME, validate_docker_installation
from .context_manager import BuildContextManager

_logger = logging.getLogger(__name__)


class DockerBuilder(AbstractBuilder):
    """Builds a docker image for a project.

    Attributes:
        builder_config (Dict[str, Any]): The builder config.

    """

    builder_type = "docker"
    target_platform = "linux/amd64"

    def __init__(
        self,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        config: Dict[str, Any],
    ):
        """Initialize a DockerBuilder.

        Arguments:
            environment (AbstractEnvironment): The environment to use.
            registry (AbstractRegistry): The registry to use.

        Raises:
            LaunchError: If docker is not installed
        """
        self.environment = environment  # Docker builder doesn't actually use this.
        self.registry = registry
        self.config = config

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
    ) -> "DockerBuilder":
        """Create a DockerBuilder from a config.

        Arguments:
            config (Dict[str, Any]): The config.
            registry (AbstractRegistry): The registry to use.
            verify (bool, optional): Whether to verify the functionality of the builder.
            login (bool, optional): Whether to login to the registry.

        Returns:
            DockerBuilder: The DockerBuilder.
        """
        # If the user provided a destination URI in the builder config
        # we use that as the registry.
        image_uri = config.get("destination")
        if image_uri:
            if registry is not None:
                wandb.termwarn(
                    f"{LOG_PREFIX}Overriding registry from registry config"
                    f" with {image_uri} from builder config."
                )
            registry = registry_from_uri(image_uri)

        return cls(environment, registry, config)

    async def verify(self) -> None:
        """Verify the builder."""
        await validate_docker_installation()

    async def login(self) -> None:
        """Login to the registry."""
        if isinstance(self.registry, LocalRegistry):
            _logger.info(f"{LOG_PREFIX}No registry configured, skipping login.")
        elif isinstance(self.registry, AnonynmousRegistry):
            _logger.info(f"{LOG_PREFIX}Anonymous registry, skipping login.")
        else:
            username, password = await self.registry.get_username_password()
            login = event_loop_thread_exec(docker.login)
            await login(username, password, self.registry.uri)

    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> str:
        """Build the image for the given project.

        Arguments:
            launch_project (LaunchProject): The project to build.
            entrypoint (EntryPoint): The entrypoint to use.
        """
        await self.verify()
        await self.login()

        build_context_manager = BuildContextManager(launch_project=launch_project)
        build_ctx_path, image_tag = build_context_manager.create_build_context("docker")
        dockerfile = os.path.join(build_ctx_path, _WANDB_DOCKERFILE_NAME)
        repository = None if not self.registry else await self.registry.get_repo_uri()

        # if repo is set, use the repo name as the image name
        if repository:
            image_uri = f"{repository}:{image_tag}"
        # otherwise, base the image name off of the source
        # which the launch_project checks in image_name
        else:
            image_uri = f"{launch_project.image_name}:{image_tag}"

        if (
            not launch_project.build_required()
            and await self.registry.check_image_exists(image_uri)
        ):
            return image_uri

        _logger.info(
            f"image {image_uri} does not already exist in repository, building."
        )
        try:
            output = await event_loop_thread_exec(docker.build)(
                tags=[image_uri],
                file=dockerfile,
                context_path=build_ctx_path,
                platform=self.config.get("platform"),
            )

            warn_failed_packages_from_build_logs(
                output, image_uri, launch_project.api, job_tracker
            )

        except docker.DockerError as e:
            if job_tracker:
                job_tracker.set_err_stage("build")
            raise LaunchDockerError(f"Error communicating with docker client: {e}")

        try:
            os.remove(build_ctx_path)
        except Exception:
            _msg = f"{LOG_PREFIX}Temporary docker context file {build_ctx_path} was not deleted."
            _logger.info(_msg)

        if repository:
            reg, tag = image_uri.split(":")
            wandb.termlog(f"{LOG_PREFIX}Pushing image {image_uri}")
            push_resp = await event_loop_thread_exec(docker.push)(reg, tag)
            if push_resp is None:
                raise LaunchError("Failed to push image to repository")
            elif (
                launch_project.resource == "sagemaker"
                and f"The push refers to repository [{repository}]" not in push_resp
            ):
                raise LaunchError(f"Unable to push image to ECR, response: {push_resp}")

        return image_uri
