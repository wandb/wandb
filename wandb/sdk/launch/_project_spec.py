"""Convert launch arguments into a runnable wandb launch script.

Arguments can come from a launch spec or call to wandb launch.
"""
import enum
import json
import logging
import os
import tempfile
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

import wandb
import wandb.docker as docker
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch import utils
from wandb.sdk.lib.runid import generate_id

from .errors import LaunchError
from .utils import LOG_PREFIX, recursive_macro_sub

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

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
        sweep_id: Optional[str] = None,
    ):
        if uri is not None and utils.is_bare_wandb_uri(uri):
            uri = api.settings("base_url") + uri
            _logger.info(f"{LOG_PREFIX}Updating uri with base uri: {uri}")
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
        self.accelerator_base_image: Optional[str] = resource_args_build.get(
            "accelerator", {}
        ).get("base_image") or resource_args_build.get("cuda", {}).get("base_image")
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
        self.overrides = overrides
        self.override_args: List[str] = overrides.get("args", [])
        self.override_config: Dict[str, Any] = overrides.get("run_config", {})
        self.override_artifacts: Dict[str, Any] = overrides.get("artifacts", {})
        self.override_entrypoint: Optional[EntryPoint] = None
        self.override_dockerfile: Optional[str] = overrides.get("dockerfile")
        self.deps_type: Optional[str] = None
        self._runtime: Optional[str] = None
        self.run_id = run_id or generate_id()
        self._queue_name: Optional[str] = None
        self._queue_entity: Optional[str] = None
        self._run_queue_item_id: Optional[str] = None
        self._entry_point: Optional[
            EntryPoint
        ] = None  # todo: keep multiple entrypoint support?

        override_entrypoint = overrides.get("entry_point")
        if override_entrypoint:
            _logger.info("Adding override entry point")
            self.override_entrypoint = EntryPoint(
                name=self._get_entrypoint_file(override_entrypoint),
                command=override_entrypoint,
            )

        if overrides.get("sweep_id") is not None:
            _logger.info("Adding override sweep id")
            self.sweep_id = overrides["sweep_id"]
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

    def _get_entrypoint_file(self, entrypoint: List[str]) -> Optional[str]:
        if not entrypoint:
            return None
        if entrypoint[0].endswith(".py") or entrypoint[0].endswith(".sh"):
            return entrypoint[0]
        if len(entrypoint) < 2:
            return None
        return entrypoint[1]

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
            None
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

    def get_single_entry_point(self) -> Optional["EntryPoint"]:
        """Returns the first entrypoint for the project, or None if no entry point was provided because a docker image was provided."""
        # assuming project only has 1 entry point, pull that out
        # tmp fn until we figure out if we want to support multiple entry points or not
        if not self._entry_point:
            if not self.docker_image:
                raise LaunchError(
                    "Project must have at least one entry point unless docker image is specified."
                )
            return None
        return self._entry_point

    def set_entry_point(self, command: List[str]) -> "EntryPoint":
        """Add an entry point to the project."""
        assert (
            self._entry_point is None
        ), "Cannot set entry point twice. Use LaunchProject.override_entrypoint"
        new_entrypoint = EntryPoint(name=command[-1], command=command)
        self._entry_point = new_entrypoint
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
        except CommError as e:
            msg = e.message
            raise LaunchError(
                f"Error accessing job {self.job}: {msg} on {public_api.settings.get('base_url')}"
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

            if not self._entry_point:
                _, ext = os.path.splitext(program_name)
                if ext == ".py":
                    entry_point = ["python", program_name]
                elif ext == ".sh":
                    command = os.environ.get("SHELL", "bash")
                    entry_point = [command, program_name]
                else:
                    raise LaunchError(f"Unsupported entrypoint: {program_name}")
                self.set_entry_point(entry_point)
            if not self.override_args:
                self.override_args = run_info["args"]
        else:
            assert utils._GIT_URI_REGEX.match(self.uri), (
                "Non-wandb URI %s should be a Git URI" % self.uri
            )
            if not self._entry_point:
                wandb.termlog(
                    f"{LOG_PREFIX}Entry point for repo not specified, defaulting to python main.py"
                )
                self.set_entry_point(EntrypointDefaults.PYTHON)
            branch_name = utils._fetch_git_repo(
                self.project_dir, self.uri, self.git_version
            )
            if self.git_version is None:
                self.git_version = branch_name


class EntryPoint:
    """An entry point into a wandb launch specification."""

    def __init__(self, name: Optional[str], command: List[str]):
        self.name = name
        self.command = command

    def compute_command(self, user_parameters: Optional[List[str]]) -> List[str]:
        """Converts user parameter dictionary to a string."""
        ret = self.command
        if user_parameters:
            return ret + user_parameters
        return ret


def get_entry_point_command(
    entry_point: Optional["EntryPoint"], parameters: List[str]
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
        launch_spec.get("sweep_id", {}),
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
        if not launch_project._entry_point:
            wandb.termlog(
                f"{LOG_PREFIX}Entry point for repo not specified, defaulting to `python main.py`"
            )
            launch_project.set_entry_point(EntrypointDefaults.PYTHON)
    elif launch_project.source == LaunchSource.JOB:
        launch_project._fetch_job()
    else:
        launch_project._fetch_project_local(internal_api=api)

    assert launch_project.project_dir is not None
    # this prioritizes pip, and we don't support any cases where both are present conda projects when uploaded to
    # wandb become pip projects via requirements.frozen.txt, wandb doesn't preserve conda envs
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
