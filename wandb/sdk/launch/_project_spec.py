"""Convert launch arguments into a runnable wandb launch script.

Arguments can come from a launch spec or call to wandb launch.
"""
import enum
import json
import logging
import os
import tempfile
from shlex import quote
from typing import Any, Dict, List, Optional

import wandb
import wandb.docker as docker
from wandb.apis.internal import Api
from wandb.apis.public import Artifact as PublicArtifact
from wandb.errors import CommError
from wandb.sdk.lib.runid import generate_id

from . import utils
from .utils import LOG_PREFIX, LaunchError

_logger = logging.getLogger(__name__)

DEFAULT_LAUNCH_METADATA_PATH = "launch_metadata.json"

# need to make user root for sagemaker, so users have access to /opt/ml directories
# that let users create artifacts and access input data
RESOURCE_UID_MAP = {"local": 1000, "sagemaker": 0}
IMAGE_TAG_MAX_LENGTH = 32


class LaunchSource(enum.IntEnum):
    WANDB: int = 1
    GIT: int = 2
    LOCAL: int = 3
    DOCKER: int = 4
    JOB: int = 5


class EntrypointDefaults(List[str]):
    PYTHON = ["python", "main.py"]


class LaunchProject:
    """A launch project specification."""

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
    ):
        if uri is not None and utils.is_bare_wandb_uri(uri):
            uri = api.settings("base_url") + uri
            _logger.info(f"{LOG_PREFIX}Updating uri with base uri: {uri}")
        self.uri = uri
        self.job = job
        if job is not None:
            wandb.termlog(f"{LOG_PREFIX}Launching job: {job}")
        self._job_artifact: Optional[PublicArtifact] = None
        self.api = api
        self.launch_spec = launch_spec
        self.target_entity = target_entity
        self.target_project = target_project.lower()
        self.name = name  # TODO: replace with run_id
        # the builder key can be passed in through the resource args
        # but these resource_args are then passed to the appropriate
        # runner, so we need to pop the builder key out
        resource_args_build = resource_args.get(resource, {}).pop("builder", {})
        self.resource = resource
        self.resource_args = resource_args
        self.python_version: Optional[str] = launch_spec.get("python_version")
        self.cuda_base_image: Optional[str] = resource_args_build.get("cuda", {}).get(
            "base_image"
        )
        self._base_image: Optional[str] = launch_spec.get("base_image")
        self.docker_image: Optional[str] = docker_config.get(
            "docker_image"
        ) or launch_spec.get("image_uri")
        uid = RESOURCE_UID_MAP.get(resource, 1000)
        if self._base_image:
            uid = docker.get_image_uid(self._base_image)
            _logger.info(f"{LOG_PREFIX}Retrieved base image uid {uid}")
        self.docker_user_id: int = docker_config.get("user_id", uid)
        self.git_version: Optional[str] = git_info.get("version")
        self.git_repo: Optional[str] = git_info.get("repo")
        self.override_args: Dict[str, Any] = overrides.get("args", {})
        self.override_config: Dict[str, Any] = overrides.get("run_config", {})
        self.override_artifacts: Dict[str, Any] = overrides.get("artifacts", {})
        self.override_entrypoint: Optional[EntryPoint] = None
        self.deps_type: Optional[str] = None
        self._runtime: Optional[str] = None
        self.run_id = run_id or generate_id()
        self._entry_points: Dict[
            str, EntryPoint
        ] = {}  # todo: keep multiple entrypoint support?

        if overrides.get("entry_point"):
            _logger.info("Adding override entry point")
            self.override_entrypoint = self.add_entry_point(
                overrides.get("entry_point")  # type: ignore
            )
        if self.docker_image is not None:
            self.source = LaunchSource.DOCKER
            self.project_dir = None
        elif self.job is not None:
            self.source = LaunchSource.JOB
            self.project_dir = tempfile.mkdtemp()
        elif self.uri is not None and utils._is_wandb_uri(self.uri):
            _logger.info(f"URI {self.uri} indicates a wandb uri")
            self.source = LaunchSource.WANDB
            self.project_dir = tempfile.mkdtemp()
        elif self.uri is not None and utils._is_git_uri(self.uri):
            _logger.info(f"URI {self.uri} indicates a git uri")
            self.source = LaunchSource.GIT
            self.project_dir = tempfile.mkdtemp()
        elif self.uri is not None and "placeholder-" in self.uri:
            wandb.termlog(
                f"{LOG_PREFIX}Launch received placeholder URI, replacing with local path."
            )
            self.uri = os.getcwd()
            self.source = LaunchSource.LOCAL
            self.project_dir = self.uri
        else:
            _logger.info(f"URI {self.uri} indicates a local uri")
            # assume local
            if self.uri is not None and not os.path.exists(self.uri):
                raise LaunchError(
                    "Assumed URI supplied is a local path but path is not valid"
                )
            self.source = LaunchSource.LOCAL
            self.project_dir = self.uri

        self.aux_dir = tempfile.mkdtemp()
        self.clear_parameter_run_config_collisions()

    @property
    def base_image(self) -> str:
        """Returns {PROJECT}_base:{PYTHON_VERSION}."""
        # TODO: this should likely be source_project when we have it...

        # don't make up a separate base image name if user provides a docker image
        if self.docker_image is not None:
            return self.docker_image

        python_version = (self.python_version or "3").replace("+", "dev")
        generated_name = "{}_base:{}".format(
            self.target_project.replace(" ", "-"), python_version
        )
        return self._base_image or generated_name

    @property
    def image_name(self) -> str:
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

    def build_required(self) -> bool:
        """Checks the source to see if a build is required."""
        # since the image tag for images built from jobs
        # is based on the job version index, which is immutable
        # we don't need to build the image for a job if that tag
        # already exists
        if self.source != LaunchSource.JOB:
            return True
        return False

    @property
    def docker_image(self) -> Optional[str]:
        return self._docker_image

    @docker_image.setter
    def docker_image(self, value: str) -> None:
        self._docker_image = value
        self._ensure_not_docker_image_and_local_process()

    def clear_parameter_run_config_collisions(self) -> None:
        """Clear values from the override run config values if a matching key exists in the override arguments."""
        if not self.override_config:
            return
        keys = [key for key in self.override_config.keys()]
        for key in keys:
            if self.override_args.get(key):
                del self.override_config[key]

    def get_single_entry_point(self) -> Optional["EntryPoint"]:
        """Returns the first entrypoint for the project, or None if no entry point was provided because a docker image was provided."""
        # assuming project only has 1 entry point, pull that out
        # tmp fn until we figure out if we want to support multiple entry points or not
        if not self._entry_points:
            if not self.docker_image:
                raise LaunchError(
                    "Project must have at least one entry point unless docker image is specified."
                )
            return None
        return list(self._entry_points.values())[0]

    def add_entry_point(self, command: List[str]) -> "EntryPoint":
        """Add an entry point to the project."""
        entry_point = command[-1]
        new_entrypoint = EntryPoint(name=entry_point, command=command)
        self._entry_points[entry_point] = new_entrypoint
        return new_entrypoint

    def _ensure_not_docker_image_and_local_process(self) -> None:
        if self.docker_image is not None and self.resource == "local-process":
            raise LaunchError(
                "Cannot specify docker image with local-process resource runner"
            )

    def _fetch_job(self) -> None:
        public_api = wandb.apis.public.Api()
        job_dir = tempfile.mkdtemp()
        try:
            job = public_api.job(self.job, path=job_dir)
        except CommError:
            raise LaunchError(
                f"Job {self.job} not found. Jobs have the format: <entity>/<project>/<name>:<alias>"
            )
        job.configure_launch_project(self)
        self._job_artifact = job._job_artifact

    def get_image_source_string(self) -> str:
        """Returns a unique string identifying the source of an image."""
        if self.source == LaunchSource.LOCAL:
            # TODO: more correct to get a hash of local uri contents
            assert isinstance(self.uri, str)
            return self.uri
        elif self.source == LaunchSource.JOB:
            assert self._job_artifact is not None
            return f"{self._job_artifact.name}:v{self._job_artifact.version}"
        elif self.source == LaunchSource.GIT:
            assert isinstance(self.uri, str)
            ret = self.uri
            if self.git_version:
                ret += self.git_version
            return ret
        elif self.source == LaunchSource.WANDB:
            assert isinstance(self.uri, str)
            return self.uri
        elif self.source == LaunchSource.DOCKER:
            assert isinstance(self.docker_image, str)
            _logger.debug("")
            return self.docker_image
        else:
            raise LaunchError("Unknown source type when determing image source string")

    def _fetch_project_local(self, internal_api: Api) -> None:
        """Fetch a project (either wandb run or git repo) into a local directory, returning the path to the local project directory."""
        # these asserts are all guaranteed to pass, but are required by mypy
        assert self.source != LaunchSource.LOCAL and self.source != LaunchSource.JOB
        assert isinstance(self.uri, str)
        assert self.project_dir is not None
        _logger.info("Fetching project locally...")
        if utils._is_wandb_uri(self.uri):
            source_entity, source_project, source_run_name = utils.parse_wandb_uri(
                self.uri
            )
            run_info = utils.fetch_wandb_project_run_info(
                source_entity, source_project, source_run_name, internal_api
            )
            program_name = run_info.get("codePath") or run_info["program"]

            self.python_version = run_info.get("python", "3")
            downloaded_code_artifact = utils.check_and_download_code_artifacts(
                source_entity,
                source_project,
                source_run_name,
                internal_api,
                self.project_dir,
            )
            if not downloaded_code_artifact:
                if not run_info["git"]:
                    raise LaunchError(
                        "Reproducing a run requires either an associated git repo or a code artifact logged with `run.log_code()`"
                    )
                branch_name = utils._fetch_git_repo(
                    self.project_dir,
                    run_info["git"]["remote"],
                    run_info["git"]["commit"],
                )
                if self.git_version is None:
                    self.git_version = branch_name
                patch = utils.fetch_project_diff(
                    source_entity, source_project, source_run_name, internal_api
                )
                if patch:
                    utils.apply_patch(patch, self.project_dir)

                # For cases where the entry point wasn't checked into git
                if not os.path.exists(os.path.join(self.project_dir, program_name)):
                    downloaded_entrypoint = utils.download_entry_point(
                        source_entity,
                        source_project,
                        source_run_name,
                        internal_api,
                        program_name,
                        self.project_dir,
                    )

                    if not downloaded_entrypoint:
                        raise LaunchError(
                            f"Entrypoint file: {program_name} does not exist, "
                            "and could not be downloaded. Please specify the entrypoint for this run."
                        )

            if (
                "_session_history.ipynb" in os.listdir(self.project_dir)
                or ".ipynb" in program_name
            ):
                program_name = utils.convert_jupyter_notebook_to_script(
                    program_name, self.project_dir
                )

            # Download any frozen requirements
            utils.download_wandb_python_deps(
                source_entity,
                source_project,
                source_run_name,
                internal_api,
                self.project_dir,
            )

            if not self._entry_points:
                _, ext = os.path.splitext(program_name)
                if ext == ".py":
                    entry_point = ["python", program_name]
                elif ext == ".sh":
                    command = os.environ.get("SHELL", "bash")
                    entry_point = [command, program_name]
                else:
                    raise LaunchError(f"Unsupported entrypoint: {program_name}")
                self.add_entry_point(entry_point)
            self.override_args = utils.merge_parameters(
                self.override_args, run_info["args"]
            )
        else:
            assert utils._GIT_URI_REGEX.match(self.uri), (
                "Non-wandb URI %s should be a Git URI" % self.uri
            )
            if not self._entry_points:
                wandb.termlog(
                    f"{LOG_PREFIX}Entry point for repo not specified, defaulting to python main.py"
                )
                self.add_entry_point(EntrypointDefaults.PYTHON)
            branch_name = utils._fetch_git_repo(
                self.project_dir, self.uri, self.git_version
            )
            if self.git_version is None:
                self.git_version = branch_name


class EntryPoint:
    """An entry point into a wandb launch specification."""

    def __init__(self, name: str, command: List[str]):
        self.name = name
        self.command = command

    def compute_command(self, user_parameters: Optional[Dict[str, Any]]) -> List[str]:
        """Converts user parameter dictionary to a string."""
        command_arr = []
        command_arr += self.command
        extras = compute_command_args(user_parameters)
        command_arr += extras
        return command_arr


def compute_command_args(parameters: Optional[Dict[str, Any]]) -> List[str]:
    arr: List[str] = []
    if parameters is None:
        return arr
    for key, value in parameters.items():
        if value is not None:
            arr.append(f"--{key}")
            arr.append(quote(str(value)))
        else:
            arr.append(f"--{key}")
    return arr


def get_entry_point_command(
    entry_point: Optional["EntryPoint"], parameters: Dict[str, Any]
) -> List[str]:
    """Returns the shell command to execute in order to run the specified entry point.

    Arguments:
    entry_point: Entry point to run
    parameters: Parameters (dictionary) for the entry point command

    Returns:
        List of strings representing the shell command to be executed
    """
    if entry_point is None:
        return []
    return entry_point.compute_command(parameters)


def create_project_from_spec(launch_spec: Dict[str, Any], api: Api) -> LaunchProject:
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
        launch_spec.get("resource", None),
        launch_spec.get("resource_args", {}),
        launch_spec.get("run_id", None),
    )


def fetch_and_validate_project(
    launch_project: LaunchProject, api: Api
) -> LaunchProject:
    """Fetches a project into a local directory, adds the config values to the directory, and validates the first entrypoint for the project.

    Arguments:
    launch_project: LaunchProject to fetch and validate.
    api: Instance of wandb.apis.internal Api

    Returns:
        A validated `LaunchProject` object.

    """
    if launch_project.source == LaunchSource.DOCKER:
        return launch_project
    if launch_project.source == LaunchSource.LOCAL:
        if not launch_project._entry_points:
            wandb.termlog(
                f"{LOG_PREFIX}Entry point for repo not specified, defaulting to `python main.py`"
            )
            launch_project.add_entry_point(EntrypointDefaults.PYTHON)
    elif launch_project.source == LaunchSource.JOB:
        launch_project._fetch_job()
    else:
        launch_project._fetch_project_local(internal_api=api)

    assert launch_project.project_dir is not None
    # this prioritizes pip, and we don't support any cases where both are present
    # conda projects when uploaded to wandb become pip projects via requirements.frozen.txt, wandb doesn't preserve conda envs
    if os.path.exists(
        os.path.join(launch_project.project_dir, "requirements.txt")
    ) or os.path.exists(
        os.path.join(launch_project.project_dir, "requirements.frozen.txt")
    ):
        launch_project.deps_type = "pip"
    elif os.path.exists(os.path.join(launch_project.project_dir, "environment.yml")):
        launch_project.deps_type = "conda"

    return launch_project


def create_metadata_file(
    launch_project: LaunchProject,
    image_uri: str,
    sanitized_entrypoint_str: str,
    sanitized_dockerfile_contents: str,
) -> None:
    assert launch_project.project_dir is not None
    with open(
        os.path.join(launch_project.project_dir, DEFAULT_LAUNCH_METADATA_PATH),
        "w",
    ) as f:
        json.dump(
            {
                **launch_project.launch_spec,
                "image_uri": image_uri,
                "command": sanitized_entrypoint_str,
                "dockerfile_contents": sanitized_dockerfile_contents,
            },
            f,
        )
