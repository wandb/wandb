import hashlib
import logging
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dockerpycreds.utils import find_executable  # type: ignore

import wandb
import wandb.env
from wandb.apis.internal import Api
from wandb.sdk.launch.loader import (
    builder_from_config,
    environment_from_config,
    registry_from_config,
)

from .._project_spec import EntryPoint, EntrypointDefaults, LaunchProject
from ..errors import ExecutionError, LaunchError
from ..utils import (
    LAUNCH_CONFIG_FILE,
    LOG_PREFIX,
    event_loop_thread_exec,
    resolve_build_and_registry_config,
)

_logger = logging.getLogger(__name__)


_WANDB_DOCKERFILE_NAME = "Dockerfile.wandb"


async def validate_docker_installation() -> None:
    """Verify if Docker is installed on host machine."""
    find_exec = event_loop_thread_exec(find_executable)
    if not await find_exec("docker"):
        raise ExecutionError(
            "Could not find Docker executable. "
            "Ensure Docker is installed as per the instructions "
            "at https://docs.docker.com/install/overview/."
        )


def join(split_command: List[str]) -> str:
    """Return a shell-escaped string from *split_command*.

    Also remove quotes from double quoted strings. Ex:
    "'local container queue'" --> "local container queue"
    """
    return " ".join(shlex.quote(arg.replace("'", "")) for arg in split_command)


# Why is this in here?
def construct_agent_configs(
    launch_config: Optional[Dict] = None,
    build_config: Optional[Dict] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    registry_config = None
    environment_config = None
    if launch_config is not None:
        build_config = launch_config.get("builder")
        registry_config = launch_config.get("registry")

    default_launch_config = None
    if os.path.exists(os.path.expanduser(LAUNCH_CONFIG_FILE)):
        with open(os.path.expanduser(LAUNCH_CONFIG_FILE)) as f:
            default_launch_config = (
                yaml.safe_load(f) or {}
            )  # In case the config is empty, we want it to be {} instead of None.
        environment_config = default_launch_config.get("environment")

    build_config, registry_config = resolve_build_and_registry_config(
        default_launch_config, build_config, registry_config
    )

    return environment_config, build_config, registry_config


async def build_image_from_project(
    launch_project: LaunchProject,
    api: Api,
    launch_config: Dict[str, Any],
) -> str:
    """Construct a docker image from a project and returns the URI of the image.

    Arguments:
        launch_project: The project to build an image from.
        api: The API object to use for fetching the project.
        launch_config: The launch config to use for building the image.

    Returns:
        The URI of the built image.
    """
    assert launch_project.uri, "To build an image on queue a URI must be set."
    launch_config = launch_config or {}
    env_config = launch_config.get("environment", {})
    if not isinstance(env_config, dict):
        wrong_type = type(env_config).__name__
        raise LaunchError(
            f"Invalid environment config: {env_config} of type {wrong_type} "
            "loaded from launch config. Expected dict."
        )
    environment = environment_from_config(env_config)

    registry_config = launch_config.get("registry", {})
    if not isinstance(registry_config, dict):
        wrong_type = type(registry_config).__name__
        raise LaunchError(
            f"Invalid registry config: {registry_config} of type {wrong_type}"
            " loaded from launch config. Expected dict."
        )
    registry = registry_from_config(registry_config, environment)

    builder_config = launch_config.get("builder", {})
    if not isinstance(builder_config, dict):
        wrong_type = type(builder_config).__name__
        raise LaunchError(
            f"Invalid builder config: {builder_config} of type {wrong_type} "
            "loaded from launch config. Expected dict."
        )
    builder = builder_from_config(builder_config, environment, registry)

    if not builder:
        raise LaunchError("Unable to build image. No builder found.")

    launch_project.fetch_and_validate_project()

    entry_point: EntryPoint = launch_project.get_job_entry_point() or EntryPoint(
        name=EntrypointDefaults.PYTHON[-1],
        command=EntrypointDefaults.PYTHON,
    )
    wandb.termlog(f"{LOG_PREFIX}Building docker image from uri source")
    image_uri = await builder.build_image(launch_project, entry_point)
    if not image_uri:
        raise LaunchError("Error building image uri")
    else:
        return image_uri


def image_tag_from_dockerfile_and_source(
    launch_project: LaunchProject, dockerfile_contents: str
) -> str:
    """Hashes the source and dockerfile contents into a unique tag."""
    image_source_string = launch_project.get_image_source_string()
    unique_id_string = image_source_string + dockerfile_contents
    image_tag = hashlib.sha256(unique_id_string.encode("utf-8")).hexdigest()[:8]
    return image_tag
