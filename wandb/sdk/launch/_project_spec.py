import enum
import logging
import os
from shlex import quote
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb.apis.internal import Api
from wandb.errors import Error as ExecutionError, LaunchError
from wandb.sdk.lib.runid import generate_id

from . import utils


_logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "launch_override_config.json"


class LaunchSource(enum.IntEnum):
    WANDB: int = 1
    GIT: int = 2
    LOCAL: int = 3


class LaunchProject(object):
    """A launch project specification."""

    def __init__(
        self,
        uri: str,
        target_entity: str,
        target_project: str,
        name: Optional[str],
        docker_config: Dict[str, Any],
        git_info: Dict[str, str],
        overrides: Dict[str, Any],
    ):

        self.uri = uri
        self.target_entity = target_entity
        self.target_project = target_project
        self.name = name
        self.docker_image: Optional[str] = docker_config.get("docker_image")
        self.docker_user_id: int = docker_config.get("user_id", 1000)
        self.git_version: Optional[str] = git_info.get("version")
        self.git_repo: Optional[str] = git_info.get("repo")
        self.override_args: Dict[str, Any] = overrides.get("args", {})
        self.override_config: Dict[str, Any] = overrides.get("run_config", {})
        self._runtime: Optional[str] = None
        self._entry_points: Dict[
            str, EntryPoint
        ] = {}  # todo: keep multiple entrypoint support?
        if "entry_point" in overrides:
            self.add_entry_point(overrides["entry_point"])

        if utils._is_wandb_uri(self.uri):
            self.source = LaunchSource.WANDB
            self.project_dir = tempfile.mkdtemp()
        elif utils._is_git_uri(self.uri):
            self.source = LaunchSource.GIT
            self.project_dir = tempfile.mkdtemp()
        else:
            # assume local
            if not os.path.exists(self.uri):
                raise LaunchError(
                    "Assumed URI supplied is a local path but path is not valid"
                )
            self.source = LaunchSource.LOCAL
            self.project_dir = self.uri

        self.run_id = generate_id()

        self.clear_parameter_run_config_collisions()

    def clear_parameter_run_config_collisions(self) -> None:
        """Clear values from the overide run config values if a matching key exists in the override arguments."""
        if not self.override_config:
            return
        keys = [key for key in self.override_config.keys()]
        for key in keys:
            if self.override_args.get(key):
                del self.override_config[key]

    def get_single_entry_point(self) -> "EntryPoint":
        """Returns the first entrypoint for the project."""
        # assuming project only has 1 entry point, pull that out
        # tmp fn until we figure out if we wanna support multiple entry points or not
        if len(self._entry_points) != 1:
            raise Exception("LaunchProject must have exactly one entry point")
        return list(self._entry_points.values())[0]

    def add_entry_point(self, entry_point: str) -> "EntryPoint":
        """Adds an entry point to the project."""
        _, file_extension = os.path.splitext(entry_point)
        ext_to_cmd = {".py": "python", ".sh": os.environ.get("SHELL", "bash")}
        if file_extension in ext_to_cmd:
            command = "%s %s" % (ext_to_cmd[file_extension], quote(entry_point))
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

    def _fetch_project_local(self, api: Api) -> None:
        """Fetch a project into a local directory, returning the path to the local project directory."""
        assert self.source != LaunchSource.LOCAL
        parsed_uri = self.uri
        if utils._is_wandb_uri(self.uri):
            run_info = utils.fetch_wandb_project_run_info(self.uri, api)
            if not run_info["git"]:
                raise ExecutionError("Run must have git repo associated")
            utils._fetch_git_repo(
                self.project_dir, run_info["git"]["remote"], run_info["git"]["commit"]
            )
            patch = utils.fetch_project_diff(self.uri, api)
            if run_info.get("python"):
                self._runtime = "python-{}".format(run_info["python"])
            if patch:
                utils.apply_patch(patch, self.project_dir)

            if not self._entry_points:
                self.add_entry_point(run_info["program"])

            self.override_args = utils.merge_parameters(
                self.override_args, run_info["args"]
            )
        else:
            assert utils._GIT_URI_REGEX.match(parsed_uri), (
                "Non-wandb URI %s should be a Git URI" % parsed_uri
            )

            if not self._entry_points:
                wandb.termlog(
                    "Entry point for repo not specified, defaulting to main.py"
                )
                self.add_entry_point("main.py")

            utils._fetch_git_repo(self.project_dir, parsed_uri, self.git_version)


class EntryPoint(object):
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
                "--%s %s" % (key, value) if value is not None else "--%s" % (key)
                for key, value in extra_params.items()
            ]
        )
        return " ".join(command_arr)

    @staticmethod
    def _sanitize_param_dict(param_dict: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Sanitizes a dictionary of paramaeters, quoting values, except for keys with None values."""
        return {
            (str(key)): (quote(str(value)) if value is not None else None)
            for key, value in param_dict.items()
        }


def get_entry_point_command(
    entry_point: "EntryPoint", parameters: Dict[str, Any]
) -> List[str]:
    """Returns the shell command to execute in order to run the specified entry point.

    Arguments:
    entry_point: Entry point to run
    parameters: Parameters (dictionary) for the entry point command

    Returns:
        List of strings representing the shell command to be executed
    """
    commands = []
    commands.append(entry_point.compute_command(parameters))
    return commands


def create_project_from_spec(launch_spec: Dict[str, Any], api: Api) -> LaunchProject:
    """Constructs a LaunchProject instance using a launch spec.

    Arguments:
    launch_spec: Dictionary representation of launch spec
    api: Instance of wandb.apis.internal Api

    Returns:
        An initialized `LaunchProject` object
    """
    uri = launch_spec["uri"]

    name: Optional[str] = None
    if launch_spec.get("name"):
        name = launch_spec["name"]

    return LaunchProject(
        uri,
        launch_spec["entity"],
        launch_spec["project"],
        name,
        launch_spec.get("docker", {}),
        launch_spec.get("git", {}),
        launch_spec.get("overrides", {}),
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
    if launch_project.source == LaunchSource.LOCAL:
        if not launch_project._entry_points:
            wandb.termlog("Entry point for repo not specified, defaulting to main.py")
            launch_project.add_entry_point("main.py")
    else:
        launch_project._fetch_project_local(api=api)
    first_entry_point = list(launch_project._entry_points.keys())[0]
    launch_project.get_entry_point(first_entry_point)._validate_parameters(
        launch_project.override_args
    )
    return launch_project
