"""Internal utilities for parsing MLproject YAML files."""

import os
from shlex import quote

import six
from wandb import util
from wandb.errors import Error as ExecutionException
import yaml
import tempfile
import logging
import urllib.parse
from distutils import dir_util

from . import utils

_logger = logging.getLogger(__name__)

MLPROJECT_FILE_NAME = "mlproject"
class Project(object):
    """A project specification loaded from an MLproject file in the passed-in directory."""
    # @@@ todo: we should expand this to store more info beyond local dir stuff

    def __init__(self, uri, name, version, entry_points, parameters):

        self.uri = uri
        self.name = name        # todo: what to do for default names
        if self.name is None and utils._is_wandb_uri(uri):
            _, wandb_project, wandb_name = utils.parse_wandb_uri(uri)
            self.name = "{}_{}".format(wandb_project, wandb_name)
        self.version = version
        self._entry_points = {}
        for ep in entry_points:
            self.add_entry_point(ep)
        self.parameters = parameters
        self.dir = None
        # todo: better way of storing docker/anyscale/etc tracking info
        self.docker_env = {}

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
            new_entrypoint = EntryPoint(name=entry_point, parameters={}, command=command)
            self._entry_points[entry_point] = new_entrypoint
            return new_entrypoint
        raise ExecutionException(
            "Could not find {0} among entry points {1} or interpret {0} as a "
            "runnable script. Supported script file extensions: "
            "{2}".format(
                entry_point, list(self._entry_points.keys()), list(ext_to_cmd.keys())
            )
        )

    def get_entry_point(self, entry_point):
        if entry_point in self._entry_points:
            return self._entry_points[entry_point]
        return self.add_entry_point(entry_point)

    def _fetch_project_local(self, api, version=None):   # @@@ uri parsing move further up
        """
        Fetch a project into a local directory, returning the path to the local project directory.
        """
        parsed_uri, subdirectory = utils._parse_subdirectory(self.uri)
        use_temp_dst_dir = utils._is_zip_uri(parsed_uri) or not utils._is_local_uri(parsed_uri)
        dst_dir = tempfile.mkdtemp() if use_temp_dst_dir else parsed_uri
        if use_temp_dst_dir:
            _logger.info("=== Fetching project from %s into %s ===", self.uri, dst_dir)
        if utils._is_zip_uri(parsed_uri):
            if utils._is_file_uri(parsed_uri):
                parsed_file_uri = urllib.parse.urlparse(urllib.parse.unquote(parsed_uri))
                parsed_uri = os.path.join(parsed_file_uri.netloc, parsed_file_uri.path)
            utils._unzip_repo(
                zip_file=(
                    parsed_uri if utils._is_local_uri(parsed_uri) else utils._fetch_zip_repo(parsed_uri)
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
            run_info = utils.fetch_wandb_project_run_info(self.uri, api)   # @@@ fetch project run info
            if not run_info["git"]:
                raise ExecutionException("Run must have git repo associated")
            utils._fetch_git_repo(run_info["git"]["remote"], run_info["git"]["commit"], dst_dir)  # @@@ git repo
            utils._create_ml_project_file_from_run_info(dst_dir, run_info)
        else:
            assert utils._GIT_URI_REGEX.match(parsed_uri), (
                "Non-local URI %s should be a Git URI" % parsed_uri
            )
            utils._fetch_git_repo(parsed_uri, version, dst_dir)
        res = os.path.abspath(os.path.join(dst_dir, subdirectory))
        if not os.path.exists(res):
            raise ExecutionException(
                "Could not find subdirectory %s of %s" % (subdirectory, dst_dir)
            )
        self.dir = res
        return res


class EntryPoint(object):
    """An entry point in an MLproject specification."""

    def __init__(self, name, parameters, command):
        self.name = name
        self.parameters = {k: Parameter(k, v) for (k, v) in parameters.items()}
        self.command = command

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

    def compute_parameters(self, user_parameters, storage_dir):
        """
        Given a dict mapping user-specified param names to values, computes parameters to
        substitute into the command for this entry point. Returns a tuple (params, extra_params)
        where `params` contains key-value pairs for parameters specified in the entry point
        definition, and `extra_params` contains key-value pairs for additional parameters passed
        by the user.
        Note that resolving parameter values can be a heavy operation, e.g. if a remote URI is
        passed for a parameter of type `path`, we download the URI to a local path within
        `storage_dir` and substitute in the local path as the parameter value.
        If `storage_dir` is `None`, report path will be return as parameter.
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
            final_params[key] = param_obj.compute_value(
                value, storage_dir, key_position
            )
        for key in user_parameters:
            if key not in final_params:
                extra_params[key] = user_parameters[key]
        return (
            self._sanitize_param_dict(final_params),
            self._sanitize_param_dict(extra_params),
        )

    def compute_command(self, user_parameters, storage_dir):
        params, extra_params = self.compute_parameters(user_parameters, storage_dir)
        command_with_params = self.command.format(**params)
        command_arr = [command_with_params]
        command_arr.extend(
            ["--%s %s" % (key, value) for key, value in extra_params.items()]
        )
        return " ".join(command_arr)

    @staticmethod
    def _sanitize_param_dict(param_dict):
        return {str(key): quote(str(value)) for key, value in param_dict.items()}


class Parameter(object):
    """A parameter in an MLproject entry point."""

    def __init__(self, name, yaml_obj):
        self.name = name
        if isinstance(yaml_obj, six.string_types):
            self.type = yaml_obj
            self.default = None
        else:
            self.type = yaml_obj.get("type", "string")
            self.default = yaml_obj.get("default")

    def _compute_uri_value(self, user_param_value):
        if not util.is_uri(user_param_value):
            raise ExecutionException(
                "Expected URI for parameter %s but got "
                "%s" % (self.name, user_param_value)
            )
        return user_param_value

    def _compute_path_value(self, user_param_value, storage_dir, key_position):
        local_path = util.get_local_path_or_none(user_param_value)
        if local_path:
            if not os.path.exists(local_path):
                raise ExecutionException(
                    "Got value %s for parameter %s, but no such file or "
                    "directory was found." % (user_param_value, self.name)
                )
            return os.path.abspath(local_path)
        target_sub_dir = "param_{}".format(key_position)
        download_dir = os.path.join(storage_dir, target_sub_dir)
        os.mkdir(download_dir)
        raise ExecutionException("Haven't implemented artifact download yet")
        # return artifact_utils._download_artifact_from_uri(
        #    artifact_uri=user_param_value, output_path=download_dir
        # )

    def compute_value(self, param_value, storage_dir, key_position):
        if storage_dir and self.type == "path":
            return self._compute_path_value(param_value, storage_dir, key_position)
        elif self.type == "uri":
            return self._compute_uri_value(param_value)
        else:
            return param_value
