"""Convert launch arguments into a runnable wandb launch script.

Arguments can come from a launch spec or call to wandb launch.
"""

import enum
import json
import logging
import os
import shlex
import shutil
import tempfile
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

import wandb
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch.utils import get_entrypoint_file
from wandb.sdk.lib.runid import generate_id

from .errors import LaunchError
from .utils import LOG_PREFIX, recursive_macro_sub

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

_logger = logging.getLogger(__name__)


# need to make user root for sagemaker, so users have access to /opt/ml directories
# that let users create artifacts and access input data
RESOURCE_UID_MAP = {"local": 1000, "sagemaker": 0}
IMAGE_TAG_MAX_LENGTH = 32


class LaunchSource(enum.IntEnum):
    """Enumeration of possible sources for a launch project.

    Attributes:
        DOCKER: Source is a Docker image. This can happen if a user runs
            `wandb launch -d <docker-image>`.
        JOB: Source is a job. This is standard case.
        SCHEDULER: Source is a wandb sweep scheduler command.
    """

    DOCKER = 1
    JOB = 2
    SCHEDULER = 3


class LaunchProject:
    """A launch project specification.

    The LaunchProject is initialized from a raw launch spec an internal API
    object. The project encapsulates logic for taking a launch spec and converting
    it into the executable code.

    The LaunchProject needs to ultimately produce a full container spec for
    execution in docker, k8s, sagemaker, or vertex. This container spec includes:
    - container image uri
    - environment variables for configuring wandb etc.
    - entrypoint command and arguments
    - additional arguments specific to the target resource (e.g. instance type, node selector)

    This class is stateful and certain methods can only be called after
    `LaunchProject.fetch_and_validate_project()` has been called.

    Notes on the entrypoint:
    - The entrypoint is the command that will be run inside the container.
    - The LaunchProject stores two entrypoints
        - The job entrypoint is the entrypoint specified in the job's config.
        - The override entrypoint is the entrypoint specified in the launch spec.
    - The override entrypoint takes precedence over the job entrypoint.
    """

    # This init is way to long, and there are too many attributes on this sucker.
    def __init__(
        self,
        uri: Optional[str],
        job: Optional[str],
        api: Api,
        launch_spec: Dict[str, Any],
        target_entity: str,
        target_project: str,
        name: Optional[str],
        docker_config: Dict[str, Any],
        git_info: Dict[str, str],
        overrides: Dict[str, Any],
        resource: str,
        resource_args: Dict[str, Any],
        run_id: Optional[str],
        sweep_id: Optional[str] = None,
    ):
        self.uri = uri
        self.job = job
        if job is not None:
            wandb.termlog(f"{LOG_PREFIX}Launching job: {job}")
        self._job_artifact: Optional[Artifact] = None
        self.api = api
        self.launch_spec = launch_spec
        self.target_entity = target_entity
        self.target_project = target_project.lower()
        self.name = name  # TODO: replace with run_id
        # the builder key can be passed in through the resource args
        # but these resource_args are then passed to the appropriate
        # runner, so we need to pop the builder key out
        resource_args_copy = deepcopy(resource_args)
        resource_args_build = resource_args_copy.get(resource, {}).pop("builder", {})
        self.resource = resource
        self.resource_args = resource_args_copy
        self.sweep_id = sweep_id
        self.author = launch_spec.get("author")
        self.python_version: Optional[str] = launch_spec.get("python_version")
        self._job_dockerfile: Optional[str] = None
        self._job_build_context: Optional[str] = None
        self._job_base_image: Optional[str] = None
        self.accelerator_base_image: Optional[str] = resource_args_build.get(
            "accelerator", {}
        ).get("base_image") or resource_args_build.get("cuda", {}).get("base_image")
        self.docker_image: Optional[str] = docker_config.get(
            "docker_image"
        ) or launch_spec.get("image_uri")  # type: ignore [assignment]
        self.docker_user_id = docker_config.get("user_id", 1000)
        self._entry_point: Optional[EntryPoint] = (
            None  # todo: keep multiple entrypoint support?
        )
        self.init_overrides(overrides)
        self.init_source()
        self.init_git(git_info)
        self.deps_type: Optional[str] = None
        self._runtime: Optional[str] = None
        self.run_id = run_id or generate_id()
        self._queue_name: Optional[str] = None
        self._queue_entity: Optional[str] = None
        self._run_queue_item_id: Optional[str] = None

    def init_source(self) -> None:
        if self.docker_image is not None:
            self.source = LaunchSource.DOCKER
            self.project_dir = None
        elif self.job is not None:
            self.source = LaunchSource.JOB
            self.project_dir = tempfile.mkdtemp()
        elif self.uri and self.uri.startswith("placeholder"):
            self.source = LaunchSource.SCHEDULER
            self.project_dir = os.getcwd()
            self._entry_point = self.override_entrypoint

    def change_project_dir(self, new_dir: str) -> None:
        """Change the project directory to a new directory."""
        # Copy the contents of the old project dir to the new project dir.
        old_dir = self.project_dir
        if old_dir is not None:
            shutil.copytree(
                old_dir,
                new_dir,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("fsmonitor--daemon.ipc", ".git"),
            )
            shutil.rmtree(old_dir)
        self.project_dir = new_dir

    def init_git(self, git_info: Dict[str, str]) -> None:
        self.git_version = git_info.get("version")
        self.git_repo = git_info.get("repo")

    def init_overrides(self, overrides: Dict[str, Any]) -> None:
        """Initialize override attributes for a launch project."""
        self.overrides = overrides
        self.override_args: List[str] = overrides.get("args", [])
        self.override_config: Dict[str, Any] = overrides.get("run_config", {})
        self.override_artifacts: Dict[str, Any] = overrides.get("artifacts", {})
        self.override_files: Dict[str, Any] = overrides.get("files", {})
        self.override_entrypoint: Optional[EntryPoint] = None
        self.override_dockerfile: Optional[str] = overrides.get("dockerfile")
        override_entrypoint = overrides.get("entry_point")
        if override_entrypoint:
            _logger.info("Adding override entry point")
            self.override_entrypoint = EntryPoint(
                name=get_entrypoint_file(override_entrypoint),
                command=override_entrypoint,
            )

    def __repr__(self) -> str:
        """String representation of LaunchProject."""
        if self.source == LaunchSource.JOB:
            return f"{self.job}"
        return f"{self.uri}"

    @classmethod
    def from_spec(cls, launch_spec: Dict[str, Any], api: Api) -> "LaunchProject":
        """Constructs a LaunchProject instance using a launch spec.

        Arguments:
            launch_spec: Dictionary representation of launch spec
            api: Instance of wandb.apis.internal Api

        Returns:
            An initialized `LaunchProject` object
        """
        name: Optional[str] = None
        if launch_spec.get("name"):
            name = launch_spec["name"]
        return LaunchProject(
            launch_spec.get("uri"),
            launch_spec.get("job"),
            api,
            launch_spec,
            launch_spec["entity"],
            launch_spec["project"],
            name,
            launch_spec.get("docker", {}),
            launch_spec.get("git", {}),
            launch_spec.get("overrides", {}),
            launch_spec.get("resource", None),  # type: ignore [arg-type]
            launch_spec.get("resource_args", {}),
            launch_spec.get("run_id", None),
            launch_spec.get("sweep_id", {}),
        )

    @property
    def job_dockerfile(self) -> Optional[str]:
        return self._job_dockerfile

    @property
    def job_build_context(self) -> Optional[str]:
        return self._job_build_context

    @property
    def job_base_image(self) -> Optional[str]:
        return self._job_base_image

    def set_job_dockerfile(self, dockerfile: str) -> None:
        self._job_dockerfile = dockerfile

    def set_job_build_context(self, build_context: str) -> None:
        self._job_build_context = build_context

    def set_job_base_image(self, base_image: str) -> None:
        self._job_base_image = base_image

    @property
    def image_name(self) -> str:
        if self.job_base_image is not None:
            return self.job_base_image
        if self.docker_image is not None:
            return self.docker_image
        elif self.uri is not None:
            cleaned_uri = self.uri.replace("https://", "/")
            first_sep = cleaned_uri.find("/")
            shortened_uri = cleaned_uri[first_sep:]
            return wandb.util.make_docker_image_name_safe(shortened_uri)
        else:
            # this will always pass since one of these 3 is required
            assert self.job is not None
            return wandb.util.make_docker_image_name_safe(self.job.split(":")[0])

    @property
    def queue_name(self) -> Optional[str]:
        return self._queue_name

    @queue_name.setter
    def queue_name(self, value: str) -> None:
        self._queue_name = value

    @property
    def queue_entity(self) -> Optional[str]:
        return self._queue_entity

    @queue_entity.setter
    def queue_entity(self, value: str) -> None:
        self._queue_entity = value

    @property
    def run_queue_item_id(self) -> Optional[str]:
        return self._run_queue_item_id

    @run_queue_item_id.setter
    def run_queue_item_id(self, value: str) -> None:
        self._run_queue_item_id = value

    def fill_macros(self, image: str) -> Dict[str, Any]:
        """Substitute values for macros in resource arguments.

        Certain macros can be used in resource args. These macros allow the
        user to set resource args dynamically in the context of the
        run being launched. The macros are given in the ${macro} format. The
        following macros are currently supported:

        ${project_name} - the name of the project the run is being launched to.
        ${entity_name} - the owner of the project the run being launched to.
        ${run_id} - the id of the run being launched.
        ${run_name} - the name of the run that is launching.
        ${image_uri} - the URI of the container image for this run.

        Additionally, you may use ${<ENV-VAR-NAME>} to refer to the value of any
        environment variables that you plan to set in the environment of any
        agents that will receive these resource args.

        Calling this method will overwrite the contents of self.resource_args
        with the substituted values.

        Args:
            image (str): The image name to fill in for ${wandb-image}.

        Returns:
            Dict[str, Any]: The resource args with all macros filled in.
        """
        update_dict = {
            "project_name": self.target_project,
            "entity_name": self.target_entity,
            "run_id": self.run_id,
            "run_name": self.name,
            "image_uri": image,
            "author": self.author,
        }
        update_dict.update(os.environ)
        result = recursive_macro_sub(self.resource_args, update_dict)
        # recursive_macro_sub given a dict returns a dict with the same keys
        # but with other input types behaves differently. The cast is for mypy.
        return cast(Dict[str, Any], result)

    def build_required(self) -> bool:
        """Checks the source to see if a build is required."""
        if self.job_base_image is not None:
            return False
        if self.source != LaunchSource.JOB:
            return True
        return False

    @property
    def docker_image(self) -> Optional[str]:
        """Returns the Docker image associated with this LaunchProject.

        This will only be set if an image_uri is being run outside a job.

        Returns:
            Optional[str]: The Docker image or None if not specified.
        """
        if self._docker_image:
            return self._docker_image
        return None

    @docker_image.setter
    def docker_image(self, value: str) -> None:
        """Sets the Docker image for the project.

        Args:
            value (str): The Docker image to set.

        Returns:
            None
        """
        self._docker_image = value
        self._ensure_not_docker_image_and_local_process()

    def get_job_entry_point(self) -> Optional["EntryPoint"]:
        """Returns the job entrypoint for the project."""
        # assuming project only has 1 entry point, pull that out
        # tmp fn until we figure out if we want to support multiple entry points or not
        if not self._entry_point:
            if not self.docker_image and not self.job_base_image:
                raise LaunchError(
                    "Project must have at least one entry point unless docker image is specified."
                )
            return None
        return self._entry_point

    def set_job_entry_point(self, command: List[str]) -> "EntryPoint":
        """Set job entrypoint for the project."""
        assert self._entry_point is None, (
            "Cannot set entry point twice. Use LaunchProject.override_entrypoint"
        )
        new_entrypoint = EntryPoint(name=command[-1], command=command)
        self._entry_point = new_entrypoint
        return new_entrypoint

    def fetch_and_validate_project(self) -> None:
        """Fetches a project into a local directory, adds the config values to the directory, and validates the first entrypoint for the project.

        Arguments:
            launch_project: LaunchProject to fetch and validate.
            api: Instance of wandb.apis.internal Api

        Returns:
            A validated `LaunchProject` object.

        """
        if self.source == LaunchSource.DOCKER:
            return
        elif self.source == LaunchSource.JOB:
            self._fetch_job()
        assert self.project_dir is not None

    # Let's make sure we document this very clearly.
    def get_image_source_string(self) -> str:
        """Returns a unique string identifying the source of an image."""
        if self.source == LaunchSource.JOB:
            assert self._job_artifact is not None
            return f"{self._job_artifact.name}:v{self._job_artifact.version}"
        elif self.source == LaunchSource.DOCKER:
            assert isinstance(self.docker_image, str)
            return self.docker_image
        else:
            raise LaunchError(
                "Unknown source type when determining image source string"
            )

    def _ensure_not_docker_image_and_local_process(self) -> None:
        """Ensure that docker image is not specified with local-process resource runner.

        Raises:
            LaunchError: If docker image is specified with local-process resource runner.
        """
        if self.docker_image is not None and self.resource == "local-process":
            raise LaunchError(
                "Cannot specify docker image with local-process resource runner"
            )

    def _fetch_job(self) -> None:
        """Fetches the job details from the public API and configures the launch project.

        Raises:
            LaunchError: If there is an error accessing the job.
        """
        public_api = wandb.apis.public.Api()
        job_dir = tempfile.mkdtemp()
        try:
            job = public_api.job(self.job, path=job_dir)
        except CommError as e:
            msg = e.message
            raise LaunchError(
                f"Error accessing job {self.job}: {msg} on {public_api.settings.get('base_url')}"
            )
        job.configure_launch_project(self)  # Why is this a method of the job?
        self._job_artifact = job._job_artifact

    def get_env_vars_dict(self, api: Api, max_env_length: int) -> Dict[str, str]:
        """Generate environment variables for the project.

        Arguments:
        launch_project: LaunchProject to generate environment variables for.

        Returns:
            Dictionary of environment variables.
        """
        env_vars = {}
        env_vars["WANDB_BASE_URL"] = api.settings("base_url")
        override_api_key = self.launch_spec.get("_wandb_api_key")
        env_vars["WANDB_API_KEY"] = override_api_key or api.api_key
        if self.target_project:
            env_vars["WANDB_PROJECT"] = self.target_project
        env_vars["WANDB_ENTITY"] = self.target_entity
        env_vars["WANDB_LAUNCH"] = "True"
        env_vars["WANDB_RUN_ID"] = self.run_id
        if self.docker_image:
            env_vars["WANDB_DOCKER"] = self.docker_image
        if self.name is not None:
            env_vars["WANDB_NAME"] = self.name
        if "author" in self.launch_spec and not override_api_key:
            env_vars["WANDB_USERNAME"] = self.launch_spec["author"]
        if self.sweep_id:
            env_vars["WANDB_SWEEP_ID"] = self.sweep_id
        if self.launch_spec.get("_resume_count", 0) > 0:
            env_vars["WANDB_RESUME"] = "allow"
        if self.queue_name:
            env_vars[wandb.env.LAUNCH_QUEUE_NAME] = self.queue_name
        if self.queue_entity:
            env_vars[wandb.env.LAUNCH_QUEUE_ENTITY] = self.queue_entity
        if self.run_queue_item_id:
            env_vars[wandb.env.LAUNCH_TRACE_ID] = self.run_queue_item_id

        _inject_wandb_config_env_vars(self.override_config, env_vars, max_env_length)
        _inject_file_overrides_env_vars(self.override_files, env_vars, max_env_length)

        artifacts = {}
        # if we're spinning up a launch process from a job
        # we should tell the run to use that artifact
        if self.job:
            artifacts = {wandb.util.LAUNCH_JOB_ARTIFACT_SLOT_NAME: self.job}
        env_vars["WANDB_ARTIFACTS"] = json.dumps(
            {**artifacts, **self.override_artifacts}
        )
        return env_vars

    def parse_existing_requirements(self) -> str:
        from packaging.requirements import InvalidRequirement, Requirement

        requirements_line = ""
        assert self.project_dir is not None
        base_requirements = os.path.join(self.project_dir, "requirements.txt")
        if os.path.exists(base_requirements):
            include_only = set()
            with open(base_requirements) as f2:
                for line in f2:
                    if line.strip() == "":
                        continue

                    try:
                        req = Requirement(line)
                        name = req.name.lower()
                        include_only.add(shlex.quote(name))
                    except InvalidRequirement:
                        _logger.warning(
                            "Unable to parse line %s in requirements.txt",
                            line,
                            exc_info=True,
                        )
                        continue

            requirements_line += "WANDB_ONLY_INCLUDE={} ".format(",".join(include_only))
            if "wandb" not in requirements_line:
                wandb.termwarn(f"{LOG_PREFIX}wandb is not present in requirements.txt.")
        return requirements_line


class EntryPoint:
    """An entry point into a wandb launch specification."""

    def __init__(self, name: Optional[str], command: List[str]):
        self.name = name
        self.command = command

    def update_entrypoint_path(self, new_path: str) -> None:
        """Updates the entrypoint path to a new path."""
        if len(self.command) == 2 and (
            self.command[0].startswith("python") or self.command[0] == "bash"
        ):
            self.command[1] = new_path


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


def _inject_file_overrides_env_vars(
    overrides: Dict[str, Any], env_dict: Dict[str, Any], maximum_env_length: int
) -> None:
    str_overrides = json.dumps(overrides)
    if len(str_overrides) <= maximum_env_length:
        env_dict["WANDB_LAUNCH_FILE_OVERRIDES"] = str_overrides
        return

    chunks = [
        str_overrides[i : i + maximum_env_length]
        for i in range(0, len(str_overrides), maximum_env_length)
    ]
    overrides_chunks_dict = {
        f"WANDB_LAUNCH_FILE_OVERRIDES_{i}": chunk for i, chunk in enumerate(chunks)
    }
    env_dict.update(overrides_chunks_dict)
