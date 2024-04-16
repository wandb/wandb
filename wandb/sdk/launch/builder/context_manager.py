import json
import logging
import os
import pathlib
import shutil
import tempfile
from typing import Tuple

import wandb
from wandb import docker
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.builder.build import image_tag_from_dockerfile_and_source
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import get_current_python_version
from wandb.util import get_module

from .build import _WANDB_DOCKERFILE_NAME

_logger = logging.getLogger(__name__)


class BuildContextManager:
    """Creates a build context for a container image from job source code."""

    def __init__(self, launch_project: LaunchProject):
        """Initialize a BuildContextManager.

        Arguments:
            launch_project: The launch project.
        """
        self.launch_project = launch_project
        assert self.launch_project.project_dir is not None
        self.directory = tempfile.mkdtemp()

    def generate_dockerfile(self, builder_type: str) -> str:
        launch_project = self.launch_project
        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )
        dockerfile = launch_project.override_dockerfile
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

        python_build_image = (
            f"python:{py_version}"  # use full python image for package installation
        )
        requirements_section = get_requirements_section(
            launch_project, self.directory, builder_type
        )
        # ----- stage 2: base -----
        python_base_setup = get_base_setup(launch_project, py_version, py_major)

        # set up user info
        username, userid = get_docker_user(launch_project, launch_project.resource)
        user_setup = get_user_setup(username, userid, launch_project.resource)
        workdir = f"/home/{username}"

        assert entry_point is not None
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

    def create_build_context(self, builder_type: str) -> Tuple[str, str]:
        """Create the build context for the container image.

        Returns:
            A pair of str: the path to the build context locally and the image
            tag computed from the Dockerfile.
        """
        entrypoint = self.launch_project.get_job_entry_point()
        assert entrypoint is not None
        assert entrypoint.name is not None
        assert self.launch_project.project_dir is not None

        # This is the case where we find Dockerfile.wandb adjacent to the
        # entrypoint. We use the entrypoint directory as the build context.
        entrypoint_dir = os.path.dirname(entrypoint.name)
        if entrypoint_dir:
            path = os.path.join(
                self.launch_project.project_dir,
                entrypoint_dir,
                _WANDB_DOCKERFILE_NAME,
            )
        else:
            path = os.path.join(self.launch_project.project_dir, _WANDB_DOCKERFILE_NAME)
        if os.path.exists(
            path
        ):  # We found a Dockerfile.wandb adjacent to the entrypoint.
            shutil.copytree(
                os.path.dirname(path),
                self.directory,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
            )
            # TODO: remove this once we make things more explicit for users
            if entrypoint_dir:
                new_path = os.path.basename(entrypoint.name)
                entrypoint = self.launch_project.get_job_entry_point()
                if entrypoint is not None:
                    entrypoint.update_entrypoint_path(new_path)
            with open(path) as f:
                docker_file_contents = f.read()
            return self.directory, image_tag_from_dockerfile_and_source(
                self.launch_project, docker_file_contents
            )

        # This is the case where we use our own Dockerfile template. We move
        # the user code into a src directory in the build context.
        dst_path = os.path.join(self.directory, "src")
        assert self.launch_project.project_dir is not None
        shutil.copytree(
            src=self.launch_project.project_dir,
            dst=dst_path,
            symlinks=True,
            ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
        )
        shutil.copy(
            os.path.join(os.path.dirname(__file__), "templates", "_wandb_bootstrap.py"),
            os.path.join(self.directory),
        )
        if self.launch_project.python_version:
            runtime_path = os.path.join(dst_path, "runtime.txt")
            with open(runtime_path, "w") as fp:
                fp.write(f"python-{self.launch_project.python_version}")

        # TODO: we likely don't need to pass the whole git repo into the container
        # with open(os.path.join(directory, ".dockerignore"), "w") as f:
        #    f.write("**/.git")
        with open(os.path.join(self.directory, _WANDB_DOCKERFILE_NAME), "w") as handle:
            docker_file_contents = self.generate_dockerfile(builder_type=builder_type)
            handle.write(docker_file_contents)
        image_tag = image_tag_from_dockerfile_and_source(
            self.launch_project, docker_file_contents
        )
        return self.directory, image_tag


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
        deps_install_line = "pip install -r requirements.txt"
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
                with open(base_path / "src" / "requirements.txt", "w") as f:
                    f.write("\n".join(project_deps))
                requirements_files += ["src/requirements.txt"]
                deps_install_line = "pip install -r requirements.txt"
                return PIP_TEMPLATE.format(
                    buildx_optional_prefix=prefix,
                    requirements_files=" ".join(requirements_files),
                    pip_install=deps_install_line,
                )

    # Else use frozen requirements from wandb run.
    if not deps_install_line and (base_path / "requirements.frozen.txt").exists():
        requirements_files += [
            "src/requirements.frozen.txt",
            "_wandb_bootstrap.py",
        ]
        deps_install_line = (
            launch_project.parse_existing_requirements() + "python _wandb_bootstrap.py"
        )

        if not deps_install_line:
            raise LaunchError(f"No dependency sources found for {launch_project}")

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
