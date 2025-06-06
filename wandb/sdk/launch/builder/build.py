import hashlib
import json
import logging
import os
import pathlib
import shlex
import shutil
from typing import Any, Dict, List, Tuple

import wandb
import wandb.env
from wandb import docker
from wandb.apis.internal import Api
from wandb.sdk.launch.loader import (
    builder_from_config,
    environment_from_config,
    registry_from_config,
)
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..errors import ExecutionError, LaunchError
from ..utils import LOG_PREFIX, event_loop_thread_exec
from .templates.dockerfile import (
    ACCELERATOR_SETUP_TEMPLATE,
    ENTRYPOINT_TEMPLATE,
    PIP_TEMPLATE,
    PYTHON_SETUP_TEMPLATE,
    USER_CREATE_TEMPLATE,
)

_logger = logging.getLogger(__name__)


_WANDB_DOCKERFILE_NAME = "Dockerfile.wandb"


async def validate_docker_installation() -> None:
    """Verify if Docker is installed on host machine."""
    find_exec = event_loop_thread_exec(shutil.which)
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

    entry_point = (
        launch_project.get_job_entry_point() or launch_project.override_entrypoint
    )
    assert entry_point is not None
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


def get_docker_user(launch_project: LaunchProject, runner_type: str) -> Tuple[str, int]:
    import getpass

    username = getpass.getuser()

    if runner_type == "sagemaker" and not launch_project.docker_image:
        # unless user has provided their own image, sagemaker must run as root but keep the name for workdir etc
        return username, 0

    userid = launch_project.docker_user_id or os.geteuid()
    return username, userid


def get_base_setup(
    launch_project: LaunchProject, py_version: str, py_major: str
) -> str:
    """Fill in the Dockerfile templates for stage 2 of build.

    CPU version is built on python, Accelerator version is built on user provided.
    """
    minor = int(py_version.split(".")[1])
    if minor < 12:
        python_base_image = f"python:{py_version}-buster"
    else:
        python_base_image = f"python:{py_version}-bookworm"
    if launch_project.accelerator_base_image:
        _logger.info(
            f"Using accelerator base image: {launch_project.accelerator_base_image}"
        )
        python_packages = [
            f"python{py_version}",
            f"libpython{py_version}",
            "python3-pip",
            "python3-setuptools",
        ]
        base_setup = ACCELERATOR_SETUP_TEMPLATE.format(
            accelerator_base_image=launch_project.accelerator_base_image,
            python_packages=" \\\n".join(python_packages),
            py_version=py_version,
        )
    else:
        python_packages = [
            "python3-dev",
            "gcc",
        ]  # gcc required for python < 3.7 for some reason
        base_setup = PYTHON_SETUP_TEMPLATE.format(py_base_image=python_base_image)
    return base_setup


# Move this into the build context manager.
def get_requirements_section(
    launch_project: LaunchProject, build_context_dir: str, builder_type: str
) -> str:
    if builder_type == "docker":
        buildx_installed = docker.is_buildx_installed()
        if not buildx_installed:
            wandb.termwarn(
                "Docker BuildX is not installed, for faster builds upgrade docker: https://github.com/docker/buildx#installing"
            )
            prefix = "RUN WANDB_DISABLE_CACHE=true"
    elif builder_type == "kaniko":
        prefix = "RUN WANDB_DISABLE_CACHE=true"
        buildx_installed = False

    if buildx_installed:
        prefix = "RUN --mount=type=cache,mode=0777,target=/root/.cache/pip"

    requirements_files = []
    deps_install_line = None

    base_path = pathlib.Path(build_context_dir)
    # If there is a requirements.txt at root of build context, use that.
    if (base_path / "src" / "requirements.txt").exists():
        requirements_files += ["src/requirements.txt"]
        deps_install_line = "pip install uv && uv pip install -r requirements.txt"
        with open(base_path / "src" / "requirements.txt") as f:
            requirements = f.readlines()
        if not any(["wandb" in r for r in requirements]):
            wandb.termwarn(f"{LOG_PREFIX}wandb is not present in requirements.txt.")
        return PIP_TEMPLATE.format(
            buildx_optional_prefix=prefix,
            requirements_files=" ".join(requirements_files),
            pip_install=deps_install_line,
        )

    # Elif there is pyproject.toml at build context, convert the dependencies
    # section to a requirements.txt and use that.
    elif (base_path / "src" / "pyproject.toml").exists():
        tomli = get_module("tomli")
        if tomli is None:
            wandb.termwarn(
                "pyproject.toml found but tomli could not be loaded. To "
                "install dependencies from pyproject.toml please run "
                "`pip install tomli` and try again."
            )
        else:
            # First try to read deps from standard pyproject format.
            with open(base_path / "src" / "pyproject.toml", "rb") as f:
                contents = tomli.load(f)
            project_deps = [
                str(d) for d in contents.get("project", {}).get("dependencies", [])
            ]
            if project_deps:
                if not any(["wandb" in d for d in project_deps]):
                    wandb.termwarn(
                        f"{LOG_PREFIX}wandb is not present as a dependency in pyproject.toml."
                    )
                with open(base_path / "src" / "requirements.txt", "w") as f:
                    f.write("\n".join(project_deps))
                requirements_files += ["src/requirements.txt"]
                deps_install_line = (
                    "pip install uv && uv pip install -r requirements.txt"
                )
                return PIP_TEMPLATE.format(
                    buildx_optional_prefix=prefix,
                    requirements_files=" ".join(requirements_files),
                    pip_install=deps_install_line,
                )

    # Else use frozen requirements from wandb run.
    if (
        not deps_install_line
        and (base_path / "src" / "requirements.frozen.txt").exists()
    ):
        requirements_files += [
            "src/requirements.frozen.txt",
            "_wandb_bootstrap.py",
        ]
        deps_install_line = (
            launch_project.parse_existing_requirements() + "python _wandb_bootstrap.py"
        )

        if not deps_install_line:
            raise LaunchError(f"No dependency sources found for {launch_project}")

        with open(base_path / "src" / "requirements.frozen.txt") as f:
            requirements = f.readlines()
        if not any(["wandb" in r for r in requirements]):
            wandb.termwarn(
                f"{LOG_PREFIX}wandb is not present in requirements.frozen.txt."
            )

        return PIP_TEMPLATE.format(
            buildx_optional_prefix=prefix,
            requirements_files=" ".join(requirements_files),
            pip_install=deps_install_line,
        )

    else:
        # this means no deps file was found
        requirements_line = "RUN mkdir -p env/"  # Docker fails otherwise
        wandb.termwarn("No requirements file found. No packages will be installed.")
        return requirements_line


def get_user_setup(username: str, userid: int, runner_type: str) -> str:
    if runner_type == "sagemaker":
        # sagemaker must run as root
        return "USER root"
    user_create = USER_CREATE_TEMPLATE.format(uid=userid, user=username)
    user_create += f"\nUSER {username}"
    return user_create


def get_entrypoint_setup(
    entry_point: EntryPoint,
) -> str:
    return ENTRYPOINT_TEMPLATE.format(entrypoint=json.dumps(entry_point.command))
