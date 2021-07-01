"""Internal utilities for parsing MLproject YAML files."""

from distutils import dir_util
import json
import logging
import os
from shlex import quote
import tempfile
import urllib.parse

import six
import wandb
from wandb import util
from wandb.errors import Error as ExecutionException
from wandb.sdk.lib.runid import generate_id

from . import utils

if wandb.TYPE_CHECKING:
    from typing import Any, Dict, List, Optional


_logger = logging.getLogger(__name__)

MLPROJECT_FILE_NAME = "mlproject"
DEFAULT_CONFIG_PATH = "launch_override_config.json"


class Project(object):
    """A project specification loaded from an MLproject file in the passed-in directory."""

    dir: Optional[str]
    run_id: str

    def __init__(
        self,
        uri: str,
        target_entity: str,
        target_project: str,
        name: str,
        version,
        entry_points: List[str],
        parameters: Dict[str, Any],
        run_config: Dict[str, Any],
    ):

        self.uri = uri
        self.name = name  # todo: what to do for default names
        if self.name is None and utils._is_wandb_uri(uri):
            _, wandb_project, wandb_name = utils.parse_wandb_uri(uri)
            self.name = "{}_{}_launch".format(wandb_project, wandb_name)
        self.target_entity = target_entity
        self.target_project = target_project

        self.version = version
        self._entry_points: Dict[str, EntryPoint] = {}
        for ep in entry_points:
            if ep:
                self.add_entry_point(ep)
        self.parameters = parameters
        self.dir = None
        self.run_config = run_config
        self.config_path = DEFAULT_CONFIG_PATH
        # todo: better way of storing docker/anyscale/etc tracking info
        self.docker_env: Dict[str, str] = {}
        # generate id for run to ack with in agent
        self.run_id = generate_id()

    def get_single_entry_point(self):
        # assuming project only has 1 entry point, pull that out
        # tmp fn until we figure out if we wanna support multiple entry points or not
        if len(self._entry_points) != 1:
            raise Exception("Project must have exactly one entry point")
        return list(self._entry_points.values())[0]

    def add_entry_point(self, entry_point):
        _, file_extension = os.path.splitext(entry_point)
        ext_to_cmd = {".py": "python", ".sh": os.environ.get("SHELL", "bash")}
        if file_extension in ext_to_cmd:
            command = "%s %s" % (ext_to_cmd[file_extension], quote(entry_point))
            if not isinstance(command, six.string_types):
                command = command.encode("utf-8")
            new_entrypoint = EntryPoint(
                name=entry_point, parameters={}, command=command
            )
            self._entry_points[entry_point] = new_entrypoint
            return new_entrypoint
        raise ExecutionException(
            "Could not find {0} among entry points {1} or interpret {0} as a "
            "runnable script. Supported script file extensions: "
            "{2}".format(
                entry_point, list(self._entry_points.keys()), list(ext_to_cmd.keys())
            )
        )

    def _merge_parameters(self, run_info_param_dict):
        for key in run_info_param_dict.keys():
            if not self.parameters.get(key):
                self.parameters[key] = run_info_param_dict[key]

    def get_entry_point(self, entry_point):
        if entry_point in self._entry_points:
            return self._entry_points[entry_point]
        return self.add_entry_point(entry_point)

    def _fetch_project_local(self, api, version=None):
        """
        Fetch a project into a local directory, returning the path to the local project directory.
        """
        parsed_uri = self.uri
        use_temp_dst_dir = utils._is_zip_uri(parsed_uri) or not utils._is_local_uri(
            parsed_uri
        )
        if use_temp_dst_dir:
            dst_dir = self.dir if self.dir else tempfile.mkdtemp()
        else:
            dst_dir = parsed_uri
        if use_temp_dst_dir:
            _logger.info("=== Fetching project from %s into %s ===", self.uri, dst_dir)
        if utils._is_zip_uri(parsed_uri):
            if utils._is_file_uri(parsed_uri):
                parsed_file_uri = urllib.parse.urlparse(
                    urllib.parse.unquote(parsed_uri)
                )
                parsed_uri = os.path.join(parsed_file_uri.netloc, parsed_file_uri.path)
            utils._unzip_repo(
                zip_file=(
                    parsed_uri
                    if utils._is_local_uri(parsed_uri)
                    else utils._fetch_zip_repo(parsed_uri)
                ),
                dst_dir=dst_dir,
            )
        elif utils._is_local_uri(self.uri):
            if version is not None:
                raise ExecutionException(
                    "Setting a version is only supported for Git project URIs"
                )
            if use_temp_dst_dir:
                dir_util.copy_tree(src=parsed_uri, dst=dst_dir)
        elif utils._is_wandb_uri(self.uri):
            run_info = utils.fetch_wandb_project_run_info(self.uri, api)
            if not run_info["git"]:
                raise ExecutionException("Run must have git repo associated")
            utils._fetch_git_repo(
                run_info["git"]["remote"], run_info["git"]["commit"], dst_dir
            )
            patch = utils.fetch_project_diff(self.uri, api)
            if patch:
                utils.apply_patch(patch, dst_dir)

            if not self._entry_points:
                self.add_entry_point(run_info["program"])

            args = utils._collect_args(run_info["args"])
            self.parameters = utils.merge_parameters(self.parameters, args)
        else:
            assert utils._GIT_URI_REGEX.match(parsed_uri), (
                "Non-local URI %s should be a Git URI" % parsed_uri
            )
            utils._fetch_git_repo(parsed_uri, version, dst_dir)
        self.dir = dst_dir
        return self.dir

    def _copy_config_local(self):
        if not self.run_config:
            return None
        if not self.dir:
            dst_dir = tempfile.mkdtemp()
            self.dir = dst_dir
        with open(os.path.join(self.dir, DEFAULT_CONFIG_PATH), "w+") as f:
            json.dump(self.run_config, f)
        return self.dir


class EntryPoint(object):
    """An entry point in an MLproject specification."""

    def __init__(self, name, command):
        self.name = name
        self.command = command
        self.parameters = {}

    def _validate_parameters(self, user_parameters):
        missing_params = []
        for name in self.parameters:
            if name not in user_parameters and self.parameters[name].default is None:
                missing_params.append(name)
        if missing_params:
            raise ExecutionException(
                "No value given for missing parameters: %s"
                % ", ".join(["'%s'" % name for name in missing_params])
            )

    def compute_parameters(self, user_parameters):
        """
        Given a dict mapping user-specified param names to values, computes parameters to
        substitute into the command for this entry point. Returns a tuple (params, extra_params)
        where `params` contains key-value pairs for parameters specified in the entry point
        definition, and `extra_params` contains key-value pairs for additional parameters passed
        by the user. Report path will be returned as parameter.
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

    def compute_command(self, user_parameters):
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
    def _sanitize_param_dict(param_dict):
        return {
            (str(key)): (quote(str(value)) if value is not None else None)
            for key, value in param_dict.items()
        }
