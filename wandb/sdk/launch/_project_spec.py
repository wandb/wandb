"""
Internal utility for converting arguments from a launch spec or call to wandb launch
into a runnable wandb launch script
"""

import enum
import json
import logging
import os
from shlex import quote
import tempfile
from typing import Any, Dict, Optional, Tuple

import wandb
from wandb.apis.internal import Api
import wandb.docker as docker
from wandb.errors import Error as ExecutionError, LaunchError
from wandb.sdk.lib.runid import generate_id

from . import utils


_logger = logging.getLogger(__name__)

DEFAULT_LAUNCH_METADATA_PATH = "launch_metadata.json"

# need to make user root for sagemaker, so users have access to /opt/ml directories
# that let users create artifacts and access input data
RESOURCE_UID_MAP = {"local": 1000, "sagemaker": 0}


class LaunchSource(enum.IntEnum):
    WANDB: int = 1
    GIT: int = 2
    LOCAL: int = 3
    DOCKER: int = 4


class LaunchProject:
    """A launch project specification."""

    def __init__(
        self,
        uri: Optional[str],
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
        cuda: Optional[bool],
    ):
        if uri is not None and utils.is_bare_wandb_uri(uri):
            uri = api.settings("base_url") + uri
            _logger.info(f"Updating uri with base uri: {uri}")
        self.uri = uri
        self.api = api
        self.launch_spec = launch_spec
        self.target_entity = target_entity
        self.target_project = target_project
        self.name = name
        self.build_image: bool = docker_config.get("build_image", False)
        self.python_version: Optional[str] = docker_config.get("python_version")
        self.cuda_version: Optional[str] = docker_config.get("cuda_version")
        self._base_image: Optional[str] = docker_config.get("base_image")
        self.docker_image: Optional[str] = docker_config.get("docker_image")
        uid = RESOURCE_UID_MAP.get(resource, 1000)
        if self._base_image:
            uid = docker.get_image_uid(self._base_image)
            _logger.info(f"Retrieved base image uid {uid}")
        self.docker_user_id: int = docker_config.get("user_id", uid)
        self.git_version: Optional[str] = git_info.get("version")
        self.git_repo: Optional[str] = git_info.get("repo")
        self.override_args: Dict[str, Any] = overrides.get("args", {})
        self.override_config: Dict[str, Any] = overrides.get("run_config", {})
        self.override_artifacts: Dict[str, Any] = overrides.get("artifacts", {})
        self.resource = resource
        self.resource_args = resource_args
        self.deps_type: Optional[str] = None
        self.cuda = cuda
        self._runtime: Optional[str] = None
        self.run_id = generate_id()
        self._entry_points: Dict[
            str, EntryPoint
        ] = {}  # todo: keep multiple entrypoint support?
        if (
            "entry_point" in overrides
            and overrides["entry_point"] is not None
            and overrides["entry_point"] != ""
        ):
            _logger.info("Adding override entry point")
            self.add_entry_point(overrides["entry_point"])
        if self.uri is None:
            if self.docker_image is None:
                raise LaunchError("Run requires a URI or a docker image")
            self.source = LaunchSource.DOCKER
            self.project_dir = None
        elif utils._is_wandb_uri(self.uri):
            _logger.info(f"URI {self.uri} indicates a wandb uri")
            self.source = LaunchSource.WANDB
            self.project_dir = tempfile.mkdtemp()
        elif utils._is_git_uri(self.uri):
            _logger.info(f"URI {self.uri} indicates a git uri")
            self.source = LaunchSource.GIT
            self.project_dir = tempfile.mkdtemp()
        else:
            _logger.info(f"URI {self.uri} indicates a local uri")
            # assume local
            if not os.path.exists(self.uri):
                raise LaunchError(
                    "Assumed URI supplied is a local path but path is not valid"
                )
            self.source = LaunchSource.LOCAL
            self.project_dir = self.uri
        if launch_spec.get("resource_args"):
            self.resource_args = launch_spec["resource_args"]

        self.aux_dir = tempfile.mkdtemp()
        self.clear_parameter_run_config_collisions()

    @property
    def base_image(self) -> str:
        """Returns {PROJECT}_base:{PYTHON_VERSION}"""
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
        """Returns {PROJECT}_launch the ultimate version will
        be tagged with a sha of the git repo"""
        # TODO: this should likely be source_project when we have it...
        return f"{self.target_project}_launch"

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

    def add_entry_point(self, entry_point: str) -> "EntryPoint":
        """Adds an entry point to the project."""
        _, file_extension = os.path.splitext(entry_point)
        ext_to_cmd = {".py": "python", ".sh": os.environ.get("SHELL", "bash")}
        if file_extension in ext_to_cmd:
            command = f"{ext_to_cmd[file_extension]} {quote(entry_point)}"
            new_entrypoint = EntryPoint(name=entry_point, command=command)
            self._entry_points[entry_point] = new_entrypoint
            return new_entrypoint
        raise ExecutionError(
            "Could not find {0} among entry points {1} or interpret {0} as a "
            "runnable script. Supported script file extensions: "
            "{2}".format(
                entry_point, list(self._entry_points.keys()), list(ext_to_cmd.keys())
            )
        )

    def get_entry_point(self, entry_point: str) -> "EntryPoint":
        """Gets the entrypoint if its set, or adds it and returns the entrypoint."""
        if entry_point in self._entry_points:
            return self._entry_points[entry_point]
        return self.add_entry_point(entry_point)

    def _fetch_project_local(self, internal_api: Api) -> None:
        """Fetch a project (either wandb run or git repo) into a local directory, returning the path to the local project directory."""
        # these asserts are all guaranteed to pass, but are required by mypy
        assert self.source != LaunchSource.LOCAL
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
            entry_point = run_info.get("codePath") or run_info["program"]

            if run_info.get("cudaVersion"):
                original_cuda_version = ".".join(run_info["cudaVersion"].split(".")[:2])

                if self.cuda is None:
                    # only set cuda on by default if cuda is None (unspecified), not False (user specifically requested cpu image)
                    wandb.termlog(
                        "Original wandb run {} was run with cuda version {}. Enabling cuda builds by default; to build on a CPU-only image, run again with --cuda=False".format(
                            source_run_name, original_cuda_version
                        )
                    )
                    self.cuda_version = original_cuda_version
                    self.cuda = True
                if (
                    self.cuda
                    and self.cuda_version
                    and self.cuda_version != original_cuda_version
                ):
                    wandb.termlog(
                        "Specified cuda version {} differs from original cuda version {}. Running with specified version {}".format(
                            self.cuda_version, original_cuda_version, self.cuda_version
                        )
                    )

            downloaded_code_artifact = utils.check_and_download_code_artifacts(
                source_entity,
                source_project,
                source_run_name,
                internal_api,
                self.project_dir,
            )

            if downloaded_code_artifact:
                self.build_image = True
            elif not downloaded_code_artifact:
                if not run_info["git"]:
                    raise ExecutionError(
                        "Reproducing a run requires either an associated git repo or a code artifact logged with `run.log_code()`"
                    )
                utils._fetch_git_repo(
                    self.project_dir,
                    run_info["git"]["remote"],
                    run_info["git"]["commit"],
                )
                patch = utils.fetch_project_diff(
                    source_entity, source_project, source_run_name, internal_api
                )

                if patch:
                    utils.apply_patch(patch, self.project_dir)
                # For cases where the entry point wasn't checked into git
                if not os.path.exists(os.path.join(self.project_dir, entry_point)):
                    downloaded_entrypoint = utils.download_entry_point(
                        source_entity,
                        source_project,
                        source_run_name,
                        internal_api,
                        entry_point,
                        self.project_dir,
                    )
                    if not downloaded_entrypoint:
                        raise LaunchError(
                            f"Entrypoint: {entry_point} does not exist, "
                            "and could not be downloaded. Please specify the entrypoint for this run."
                        )
                    # if the entrypoint is downloaded and inserted into the project dir
                    # need to rebuild image with new code
                    self.build_image = True

            if (
                "_session_history.ipynb" in os.listdir(self.project_dir)
                or ".ipynb" in entry_point
            ):
                entry_point = utils.convert_jupyter_notebook_to_script(
                    entry_point, self.project_dir
                )

            # Download any frozen requirements
            utils.download_wandb_python_deps(
                source_entity,
                source_project,
                source_run_name,
                internal_api,
                self.project_dir,
            )

            # Specify the python runtime for jupyter2docker
            self.python_version = run_info.get("python", "3")

            if not self._entry_points:
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
                    "Entry point for repo not specified, defaulting to main.py"
                )
                self.add_entry_point("main.py")
            utils._fetch_git_repo(self.project_dir, self.uri, self.git_version)


class EntryPoint:
    """An entry point into a wandb launch specification."""

    def __init__(self, name: str, command: str):
        self.name = name
        self.command = command
        self.parameters: Dict[str, Any] = {}

    def _validate_parameters(self, user_parameters: Dict[str, Any]) -> None:
        missing_params = []
        for name in self.parameters:
            if name not in user_parameters and self.parameters[name].default is None:
                missing_params.append(name)
        if missing_params:
            raise ExecutionError(
                "No value given for missing parameters: %s"
                % ", ".join(["'%s'" % name for name in missing_params])
            )

    def compute_parameters(
        self, user_parameters: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
        """Validates and sanitizes parameters dict into expected dict format.

        Given a dict mapping user-specified param names to values, computes parameters to
        substitute into the command for this entry point. Returns a tuple (params, extra_params)
        where `params` contains key-value pairs for parameters specified in the entry point
        definition, and `extra_params` contains key-value pairs for additional parameters passed
        by the user.
        """
        if user_parameters is None:
            user_parameters = {}
        # Validate params before attempting to resolve parameter values
        self._validate_parameters(user_parameters)
        final_params = {}
        extra_params = {}

        parameter_keys = list(self.parameters.keys())
        for key in parameter_keys:
            param_obj = self.parameters[key]
            key_position = parameter_keys.index(key)
            value = (
                user_parameters[key]
                if key in user_parameters
                else self.parameters[key].default
            )
            final_params[key] = param_obj.compute_value(value, key_position)
        for key in user_parameters:
            if key not in final_params:
                extra_params[key] = user_parameters[key]
        return (
            self._sanitize_param_dict(final_params),
            self._sanitize_param_dict(extra_params),
        )

    def compute_command(self, user_parameters: Optional[Dict[str, Any]]) -> str:
        """Converts user parameter dictionary to a string."""
        params, extra_params = self.compute_parameters(user_parameters)
        command_with_params = self.command.format(**params)
        command_arr = [command_with_params]
        command_arr.extend(
            [
                f"--{key} {value}" if value is not None else f"--{key}"
                for key, value in extra_params.items()
            ]
        )
        return " ".join(command_arr)

    @staticmethod
    def _sanitize_param_dict(param_dict: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Sanitizes a dictionary of parameters, quoting values, except for keys with None values."""
        return {
            (str(key)): (quote(str(value)) if value is not None else None)
            for key, value in param_dict.items()
        }


def get_entry_point_command(
    entry_point: Optional["EntryPoint"], parameters: Dict[str, Any]
) -> str:
    """Returns the shell command to execute in order to run the specified entry point.

    Arguments:
    entry_point: Entry point to run
    parameters: Parameters (dictionary) for the entry point command

    Returns:
        List of strings representing the shell command to be executed
    """
    if entry_point is None:
        return ""
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
        api,
        launch_spec,
        launch_spec["entity"],
        launch_spec["project"],
        name,
        launch_spec.get("docker", {}),
        launch_spec.get("git", {}),
        launch_spec.get("overrides", {}),
        launch_spec.get("resource", "local"),
        launch_spec.get("resource_args", {}),
        launch_spec.get("cuda", None),
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
            wandb.termlog("Entry point for repo not specified, defaulting to main.py")
            launch_project.add_entry_point("main.py")
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

    first_entry_point = list(launch_project._entry_points.keys())[0]
    _logger.info("validating entrypoint parameters")
    launch_project.get_entry_point(first_entry_point)._validate_parameters(
        launch_project.override_args
    )
    return launch_project


def create_metadata_file(
    launch_project: LaunchProject,
    image_uri: str,
    sanitized_entrypoint_str: str,
    docker_args: Dict[str, Any],
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
                "docker_args": docker_args,
                "dockerfile_contents": sanitized_dockerfile_contents,
            },
            f,
        )
