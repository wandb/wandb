import logging
import os
import shutil
import tempfile
from typing import Tuple

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.builder.build import image_tag_from_dockerfile_and_source
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import get_current_python_version

from .build import (
    _WANDB_DOCKERFILE_NAME,
    get_base_setup,
    get_docker_user,
    get_entrypoint_setup,
    get_requirements_section,
    get_user_setup,
)
from .templates.dockerfile import DOCKERFILE_TEMPLATE

_logger = logging.getLogger(__name__)


class BuildContextManager:
    """Creates a build context for a container image from job source code.

    The dockerfile and build context may be specified by the job itself. If not,
    the behavior for creating the build context is as follows:

    - If a Dockerfile.wandb is found adjacent to the entrypoint, the directory
        containing the entrypoint is used as the build context and Dockerfile.wandb
        is used as the Dockerfile.

    - If `override_dockerfile` is set on the LaunchProject, the directory
        containing the Dockerfile is used as the build context and the Dockerfile
        is used as the Dockerfile. `override_dockerfile` can be set in a launch
        spec via the `-D` flag to `wandb launch` or in the `overrides` section
        of the launch drawer.

    - If no dockerfile is set, a Dockerfile is generated from the job's
        requirements and entrypoint.
    """

    def __init__(self, launch_project: LaunchProject):
        """Initialize a BuildContextManager.

        Arguments:
            launch_project: The launch project.
        """
        self._launch_project = launch_project
        assert self._launch_project.project_dir is not None
        self._directory = tempfile.mkdtemp()

    def _generate_dockerfile(self, builder_type: str) -> str:
        """Generate a Dockerfile for the container image.

        Arguments:
            builder_type: The type of builder to use. One of "docker" or "kaniko".

        Returns:
            The contents of the Dockerfile.
        """
        launch_project = self._launch_project
        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )

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
            launch_project, self._directory, builder_type
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
        entrypoint = (
            self._launch_project.get_job_entry_point()
            or self._launch_project.override_entrypoint
        )
        assert entrypoint is not None
        assert entrypoint.name is not None
        assert self._launch_project.project_dir is not None

        # we use that as the build context.
        build_context_root_dir = self._launch_project.project_dir
        job_build_context = self._launch_project.job_build_context
        if job_build_context:
            full_path = os.path.join(build_context_root_dir, job_build_context)
            if not os.path.exists(full_path):
                raise LaunchError(f"Build context does not exist at {full_path}")
            build_context_root_dir = full_path

        # This is the case where the user specifies a Dockerfile to use.
        # We use the directory containing the Dockerfile as the build context.
        override_dockerfile = self._launch_project.override_dockerfile
        if override_dockerfile:
            full_path = os.path.join(
                build_context_root_dir,
                override_dockerfile,
            )
            if not os.path.exists(full_path):
                raise LaunchError(f"Dockerfile does not exist at {full_path}")
            shutil.copytree(
                build_context_root_dir,
                self._directory,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
            )
            shutil.copy(
                full_path,
                os.path.join(self._directory, _WANDB_DOCKERFILE_NAME),
            )
            return self._directory, image_tag_from_dockerfile_and_source(
                self._launch_project, open(full_path).read()
            )

        # If the job specifies a Dockerfile, we use that as the Dockerfile.
        job_dockerfile = self._launch_project.job_dockerfile
        if job_dockerfile:
            dockerfile_path = os.path.join(build_context_root_dir, job_dockerfile)
            if not os.path.exists(dockerfile_path):
                raise LaunchError(f"Dockerfile does not exist at {dockerfile_path}")
            shutil.copytree(
                build_context_root_dir,
                self._directory,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
            )
            shutil.copy(
                dockerfile_path,
                os.path.join(self._directory, _WANDB_DOCKERFILE_NAME),
            )
            return self._directory, image_tag_from_dockerfile_and_source(
                self._launch_project, open(dockerfile_path).read()
            )

        # This is the case where we find Dockerfile.wandb adjacent to the
        # entrypoint. We use the entrypoint directory as the build context.
        entrypoint_dir = os.path.dirname(entrypoint.name)
        if entrypoint_dir:
            path = os.path.join(
                build_context_root_dir,
                entrypoint_dir,
                _WANDB_DOCKERFILE_NAME,
            )
        else:
            path = os.path.join(build_context_root_dir, _WANDB_DOCKERFILE_NAME)
        if os.path.exists(
            path
        ):  # We found a Dockerfile.wandb adjacent to the entrypoint.
            shutil.copytree(
                os.path.dirname(path),
                self._directory,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
            )
            # TODO: remove this once we make things more explicit for users
            if entrypoint_dir:
                new_path = os.path.basename(entrypoint.name)
                entrypoint = self._launch_project.get_job_entry_point()
                if entrypoint is not None:
                    entrypoint.update_entrypoint_path(new_path)
            with open(path) as f:
                docker_file_contents = f.read()
            return self._directory, image_tag_from_dockerfile_and_source(
                self._launch_project, docker_file_contents
            )

        # This is the case where we use our own Dockerfile template. We move
        # the user code into a src directory in the build context.
        dst_path = os.path.join(self._directory, "src")
        assert self._launch_project.project_dir is not None
        shutil.copytree(
            src=self._launch_project.project_dir,
            dst=dst_path,
            symlinks=True,
            ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc"),
        )
        shutil.copy(
            os.path.join(os.path.dirname(__file__), "templates", "_wandb_bootstrap.py"),
            os.path.join(self._directory),
        )
        if self._launch_project.python_version:
            runtime_path = os.path.join(dst_path, "runtime.txt")
            with open(runtime_path, "w") as fp:
                fp.write(f"python-{self._launch_project.python_version}")

        # TODO: we likely don't need to pass the whole git repo into the container
        # with open(os.path.join(directory, ".dockerignore"), "w") as f:
        #    f.write("**/.git")
        with open(os.path.join(self._directory, _WANDB_DOCKERFILE_NAME), "w") as handle:
            docker_file_contents = self._generate_dockerfile(builder_type=builder_type)
            handle.write(docker_file_contents)
        image_tag = image_tag_from_dockerfile_and_source(
            self._launch_project, docker_file_contents
        )
        return self._directory, image_tag
