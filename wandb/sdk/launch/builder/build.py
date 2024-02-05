import hashlib
import json
import logging
import os
import shlex
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import pkg_resources
import yaml
from dockerpycreds.utils import find_executable  # type: ignore
from six.moves import shlex_quote

import wandb
import wandb.docker as docker
import wandb.env
from wandb.apis.internal import Api
from wandb.sdk.launch.loader import (
    builder_from_config,
    environment_from_config,
    registry_from_config,
)

from .._project_spec import (
    EntryPoint,
    EntrypointDefaults,
    LaunchProject,
    fetch_and_validate_project,
)
from ..errors import ExecutionError, LaunchError
from ..registry.abstract import AbstractRegistry
from ..utils import (
    AZURE_CONTAINER_REGISTRY_URI_REGEX,
    ELASTIC_CONTAINER_REGISTRY_URI_REGEX,
    GCP_ARTIFACT_REGISTRY_URI_REGEX,
    LAUNCH_CONFIG_FILE,
    LOG_PREFIX,
    event_loop_thread_exec,
    resolve_build_and_registry_config,
)

_logger = logging.getLogger(__name__)


_WANDB_DOCKERFILE_NAME = "Dockerfile.wandb"


def registry_from_uri(uri: str) -> AbstractRegistry:
    """Create a registry helper object from a uri.

    This function parses the URI and determines which supported registry it
    belongs to. It then creates a registry helper object for that registry.
    The supported remote registry types are:
    - Azure Container Registry
    - Google Container Registry
    - AWS Elastic Container Registry

    The format of the URI is as follows:
    - Azure Container Registry: <registry-name>.azurecr.io/<repo-name>/<image-name>
    - Google Container Registry: <location>-docker.pkg.dev/<project-id>/<repo-name>/<image-name>
    - AWS Elastic Container Registry: <account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>/<image-name>

    Our classification of the registry is based on the domain name. For example,
    if the uri contains `.azurecr.io`, we classify it as an Azure
    Container Registry. If the uri contains `.dkr.ecr`, we classify
    it as an AWS Elastic Container Registry. If the uri contains
    `-docker.pkg.dev`, we classify it as a Google Artifact Registry.

    This function will attempt to load the approriate cloud helpers for the

    `https://` prefix is optional for all of the above.

    Arguments:
        uri: The uri to create a registry from.

    Returns:
        The registry.

    Raises:
        LaunchError: If the registry helper cannot be loaded for the given URI.
    """
    if uri.startswith("https://"):
        uri = uri[len("https://") :]

    if AZURE_CONTAINER_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.azure_container_registry import (
            AzureContainerRegistry,
        )

        return AzureContainerRegistry(uri=uri)

    elif GCP_ARTIFACT_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.google_artifact_registry import (
            GoogleArtifactRegistry,
        )

        return GoogleArtifactRegistry(uri=uri)

    elif ELASTIC_CONTAINER_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.elastic_container_registry import (
            ElasticContainerRegistry,
        )

        return ElasticContainerRegistry(uri=uri)

    else:
        raise LaunchError(f"Unsupported registry URI: {uri}. Unable to load helper.")


async def validate_docker_installation() -> None:
    """Verify if Docker is installed on host machine."""
    find_exec = event_loop_thread_exec(find_executable)
    if not await find_exec("docker"):
        raise ExecutionError(
            "Could not find Docker executable. "
            "Ensure Docker is installed as per the instructions "
            "at https://docs.docker.com/install/overview/."
        )


def get_docker_user(launch_project: LaunchProject, runner_type: str) -> Tuple[str, int]:
    import getpass

    username = getpass.getuser()

    if runner_type == "sagemaker" and not launch_project.docker_image:
        # unless user has provided their own image, sagemaker must run as root but keep the name for workdir etc
        return username, 0

    userid = launch_project.docker_user_id or os.geteuid()
    return username, userid


DOCKERFILE_TEMPLATE = """
# ----- stage 1: build -----
FROM {py_build_image} as build

# requirements section depends on pip vs conda, and presence of buildx
ENV PIP_PROGRESS_BAR off
{requirements_section}

# ----- stage 2: base -----
{base_setup}

COPY --from=build /env /env
ENV PATH="/env/bin:$PATH"

ENV SHELL /bin/bash

# some resources (eg sagemaker) must run on root
{user_setup}

WORKDIR {workdir}
RUN chown -R {uid} {workdir}

# make artifacts cache dir unrelated to build
RUN mkdir -p {workdir}/.cache && chown -R {uid} {workdir}/.cache

# copy code/etc
COPY --chown={uid} src/ {workdir}

ENV PYTHONUNBUFFERED=1

{entrypoint_section}
"""

# this goes into base_setup in TEMPLATE
PYTHON_SETUP_TEMPLATE = """
FROM {py_base_image} as base
"""

# this goes into base_setup in TEMPLATE
ACCELERATOR_SETUP_TEMPLATE = """
FROM {accelerator_base_image} as base

# make non-interactive so build doesn't block on questions
ENV DEBIAN_FRONTEND=noninteractive

# install python
RUN apt-get update -qq && apt-get install --no-install-recommends -y \
    {python_packages} \
    && apt-get -qq purge && apt-get -qq clean \
    && rm -rf /var/lib/apt/lists/*

# make sure `python` points at the right version
RUN update-alternatives --install /usr/bin/python python /usr/bin/python{py_version} 1 \
    && update-alternatives --install /usr/local/bin/python python /usr/bin/python{py_version} 1
"""

# this goes into requirements_section in TEMPLATE
PIP_TEMPLATE = """
RUN python -m venv /env
# make sure we install into the env
ENV PATH="/env/bin:$PATH"

COPY {requirements_files} ./
{buildx_optional_prefix} {pip_install}
"""

# this goes into requirements_section in TEMPLATE
CONDA_TEMPLATE = """
COPY src/environment.yml .
{buildx_optional_prefix} conda env create -f environment.yml -n env

# pack the environment so that we can transfer to the base image
RUN conda install -c conda-forge conda-pack
RUN conda pack -n env -o /tmp/env.tar && \
    mkdir /env && cd /env && tar xf /tmp/env.tar && \
    rm /tmp/env.tar
RUN /env/bin/conda-unpack
"""

USER_CREATE_TEMPLATE = """
RUN useradd \
    --create-home \
    --no-log-init \
    --shell /bin/bash \
    --gid 0 \
    --uid {uid} \
    {user} || echo ""
"""

ENTRYPOINT_TEMPLATE = """
ENTRYPOINT {entrypoint}
"""


def get_current_python_version() -> Tuple[str, str]:
    full_version = sys.version.split()[0].split(".")
    major = full_version[0]
    version = ".".join(full_version[:2]) if len(full_version) >= 2 else major + ".0"
    return version, major


def get_base_setup(
    launch_project: LaunchProject, py_version: str, py_major: str
) -> str:
    """Fill in the Dockerfile templates for stage 2 of build.

    CPU version is built on python, Accelerator version is built on user provided.
    """
    python_base_image = f"python:{py_version}-buster"
    if launch_project.accelerator_base_image:
        _logger.info(
            f"Using accelerator base image: {launch_project.accelerator_base_image}"
        )
        # accelerator base images doesn't come with python tooling
        if py_major == "2":
            python_packages = [
                f"python{py_version}",
                f"libpython{py_version}",
                "python-pip",
                "python-setuptools",
            ]
        else:
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
            "python3-dev" if py_major == "3" else "python-dev",
            "gcc",
        ]  # gcc required for python < 3.7 for some reason
        base_setup = PYTHON_SETUP_TEMPLATE.format(py_base_image=python_base_image)
    return base_setup


def get_env_vars_dict(
    launch_project: LaunchProject, api: Api, max_env_length: int
) -> Dict[str, str]:
    """Generate environment variables for the project.

    Arguments:
    launch_project: LaunchProject to generate environment variables for.

    Returns:
        Dictionary of environment variables.
    """
    env_vars = {}
    env_vars["WANDB_BASE_URL"] = api.settings("base_url")
    override_api_key = launch_project.launch_spec.get("_wandb_api_key")
    env_vars["WANDB_API_KEY"] = override_api_key or api.api_key
    if launch_project.target_project:
        env_vars["WANDB_PROJECT"] = launch_project.target_project
    env_vars["WANDB_ENTITY"] = launch_project.target_entity
    env_vars["WANDB_LAUNCH"] = "True"
    env_vars["WANDB_RUN_ID"] = launch_project.run_id
    if launch_project.docker_image:
        env_vars["WANDB_DOCKER"] = launch_project.docker_image
    if launch_project.name is not None:
        env_vars["WANDB_NAME"] = launch_project.name
    if "author" in launch_project.launch_spec and not override_api_key:
        env_vars["WANDB_USERNAME"] = launch_project.launch_spec["author"]
    if launch_project.sweep_id:
        env_vars["WANDB_SWEEP_ID"] = launch_project.sweep_id
    if launch_project.launch_spec.get("_resume_count", 0) > 0:
        env_vars["WANDB_RESUME"] = "allow"
    if launch_project.queue_name:
        env_vars[wandb.env.LAUNCH_QUEUE_NAME] = launch_project.queue_name
    if launch_project.queue_entity:
        env_vars[wandb.env.LAUNCH_QUEUE_ENTITY] = launch_project.queue_entity
    if launch_project.run_queue_item_id:
        env_vars[wandb.env.LAUNCH_TRACE_ID] = launch_project.run_queue_item_id

    _inject_wandb_config_env_vars(
        launch_project.override_config, env_vars, max_env_length
    )
    # env_vars["WANDB_CONFIG"] = json.dumps(launch_project.override_config)
    artifacts = {}
    # if we're spinning up a launch process from a job
    # we should tell the run to use that artifact
    if launch_project.job:
        artifacts = {wandb.util.LAUNCH_JOB_ARTIFACT_SLOT_NAME: launch_project.job}
    env_vars["WANDB_ARTIFACTS"] = json.dumps(
        {**artifacts, **launch_project.override_artifacts}
    )
    return env_vars


def get_requirements_section(launch_project: LaunchProject, builder_type: str) -> str:
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
    if launch_project.deps_type == "pip":
        requirements_files = []
        if launch_project.project_dir is not None and os.path.exists(
            os.path.join(launch_project.project_dir, "requirements.txt")
        ):
            requirements_files += ["src/requirements.txt"]
            pip_install_line = "pip install -r requirements.txt"
        elif launch_project.project_dir is not None and os.path.exists(
            os.path.join(launch_project.project_dir, "requirements.frozen.txt")
        ):
            # if we have frozen requirements stored, copy those over and have them take precedence
            requirements_files += ["src/requirements.frozen.txt", "_wandb_bootstrap.py"]
            pip_install_line = (
                _parse_existing_requirements(launch_project)
                + "python _wandb_bootstrap.py"
            )
        if buildx_installed:
            prefix = "RUN --mount=type=cache,mode=0777,target=/root/.cache/pip"

        requirements_line = PIP_TEMPLATE.format(
            buildx_optional_prefix=prefix,
            requirements_files=" ".join(requirements_files),
            pip_install=pip_install_line,
        )
    elif launch_project.deps_type == "conda":
        if buildx_installed:
            prefix = "RUN --mount=type=cache,mode=0777,target=/opt/conda/pkgs"
        requirements_line = CONDA_TEMPLATE.format(buildx_optional_prefix=prefix)
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


def generate_dockerfile(
    launch_project: LaunchProject,
    entry_point: EntryPoint,
    runner_type: str,
    builder_type: str,
    dockerfile: Optional[str] = None,
) -> str:
    if launch_project.project_dir is not None and dockerfile:
        path = os.path.join(launch_project.project_dir, dockerfile)
        if not os.path.exists(path):
            raise LaunchError(f"Dockerfile does not exist at {path}")
        launch_project.project_dir = os.path.dirname(path)
        wandb.termlog(f"Using dockerfile: {dockerfile}")
        return open(path).read()

    # get python versions truncated to major.minor to ensure image availability
    if launch_project.python_version:
        spl = launch_project.python_version.split(".")[:2]
        py_version, py_major = (".".join(spl), spl[0])
    else:
        py_version, py_major = get_current_python_version()

    # ----- stage 1: build -----
    if launch_project.deps_type == "pip" or launch_project.deps_type is None:
        python_build_image = (
            f"python:{py_version}"  # use full python image for package installation
        )
    elif launch_project.deps_type == "conda":
        # neither of these images are receiving regular updates, latest should be pretty stable
        python_build_image = (
            "continuumio/miniconda3:latest"
            if py_major == "3"
            else "continuumio/miniconda:latest"
        )
    requirements_section = get_requirements_section(launch_project, builder_type)
    # ----- stage 2: base -----
    python_base_setup = get_base_setup(launch_project, py_version, py_major)

    # set up user info
    username, userid = get_docker_user(launch_project, runner_type)
    user_setup = get_user_setup(username, userid, runner_type)
    workdir = f"/home/{username}"

    entrypoint_section = get_entrypoint_setup(entry_point)

    dockerfile_contents = DOCKERFILE_TEMPLATE.format(
        py_build_image=python_build_image,
        requirements_section=requirements_section,
        base_setup=python_base_setup,
        uid=userid,
        user_setup=user_setup,
        workdir=workdir,
        entrypoint_section=entrypoint_section,
    )
    return dockerfile_contents


def construct_gcp_registry_uri(
    gcp_repo: str, gcp_project: str, gcp_registry: str
) -> str:
    return "/".join([gcp_registry, gcp_project, gcp_repo])


def _parse_existing_requirements(launch_project: LaunchProject) -> str:
    requirements_line = ""
    assert launch_project.project_dir is not None
    base_requirements = os.path.join(launch_project.project_dir, "requirements.txt")
    if os.path.exists(base_requirements):
        include_only = set()
        with open(base_requirements) as f:
            iter = pkg_resources.parse_requirements(f)
            while True:
                try:
                    pkg = next(iter)
                    if hasattr(pkg, "name"):
                        name = pkg.name.lower()
                    else:
                        name = str(pkg)
                    include_only.add(shlex_quote(name))
                except StopIteration:
                    break
                # Different versions of pkg_resources throw different errors
                # just catch them all and ignore packages we can't parse
                except Exception as e:
                    _logger.warn(f"Unable to parse requirements.txt: {e}")
                    continue
        requirements_line += "WANDB_ONLY_INCLUDE={} ".format(",".join(include_only))
    return requirements_line


def _create_docker_build_ctx(
    launch_project: LaunchProject,
    dockerfile_contents: str,
) -> str:
    """Create a build context temp dir for a Dockerfile and project code."""
    assert launch_project.project_dir is not None
    directory = tempfile.mkdtemp()
    entrypoint = launch_project.get_single_entry_point()
    if entrypoint is not None:
        assert entrypoint.name is not None
        entrypoint_dir = os.path.dirname(entrypoint.name)
        if entrypoint_dir:
            path = os.path.join(
                launch_project.project_dir, entrypoint_dir, _WANDB_DOCKERFILE_NAME
            )
        else:
            path = os.path.join(launch_project.project_dir, _WANDB_DOCKERFILE_NAME)
        if os.path.exists(
            path
        ):  # We found a Dockerfile.wandb adjacent to the entrypoint.
            shutil.copytree(
                os.path.dirname(path),
                directory,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
            )
            return directory

    dst_path = os.path.join(directory, "src")
    assert launch_project.project_dir is not None
    shutil.copytree(
        src=launch_project.project_dir,
        dst=dst_path,
        symlinks=True,
        ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
    )
    shutil.copy(
        os.path.join(os.path.dirname(__file__), "templates", "_wandb_bootstrap.py"),
        os.path.join(directory),
    )
    if launch_project.python_version:
        runtime_path = os.path.join(dst_path, "runtime.txt")
        with open(runtime_path, "w") as fp:
            fp.write(f"python-{launch_project.python_version}")
    # TODO: we likely don't need to pass the whole git repo into the container
    # with open(os.path.join(directory, ".dockerignore"), "w") as f:
    #    f.write("**/.git")
    with open(os.path.join(directory, _WANDB_DOCKERFILE_NAME), "w") as handle:
        handle.write(dockerfile_contents)
    return directory


def join(split_command: List[str]) -> str:
    """Return a shell-escaped string from *split_command*.

    Also remove quotes from double quoted strings. Ex:
    "'local container queue'" --> "local container queue"
    """
    return " ".join(shlex.quote(arg.replace("'", "")) for arg in split_command)


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

    launch_project = fetch_and_validate_project(launch_project, api)

    entry_point: EntryPoint = launch_project.get_single_entry_point() or EntryPoint(
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


def _inject_wandb_config_env_vars(
    config: Dict[str, Any], env_dict: Dict[str, Any], maximum_env_length: int
) -> None:
    str_config = json.dumps(config)
    if len(str_config) <= maximum_env_length:
        env_dict["WANDB_CONFIG"] = str_config
        return

    chunks = [
        str_config[i : i + maximum_env_length]
        for i in range(0, len(str_config), maximum_env_length)
    ]
    config_chunks_dict = {f"WANDB_CONFIG_{i}": chunk for i, chunk in enumerate(chunks)}
    env_dict.update(config_chunks_dict)
