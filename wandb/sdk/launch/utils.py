# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
from distutils import dir_util
import hashlib
import json
import logging
import os
import subprocess
import re
import tempfile
import urllib.parse
import yaml
from gql import Client, gql
from gql.client import RetryError  # type: ignore
from gql.transport.requests import RequestsHTTPTransport  # type: ignore
import wandb
from wandb.errors import ExecutionException
import time
from . import _project_spec


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/]*:")
_FILE_URI_REGEX = re.compile(r"^file://.+")
_ZIP_URI_REGEX = re.compile(r".+\.zip$")
_WANDB_URI_REGEX = re.compile(r"^https://wandb")

WANDB_DOCKER_WORKDIR_PATH = "/wandb/projects/code/"

PROJECT_USE_CONDA = "USE_CONDA"
PROJECT_BUILD_DOCKER = "BUILD_DOCKER"
PROJECT_SYNCHRONOUS = "SYNCHRONOUS"
PROJECT_DOCKER_ARGS = "DOCKER_ARGS"
PROJECT_STORAGE_DIR = "STORAGE_DIR"


_logger = logging.getLogger(__name__)


def _parse_subdirectory(uri):
    # Parses a uri and returns the uri and subdirectory as separate values.
    # Uses '#' as a delimiter.
    subdirectory = ""
    parsed_uri = uri
    if "#" in uri:
        subdirectory = uri[uri.find("#") + 1 :]
        parsed_uri = uri[: uri.find("#")]
    if subdirectory and "." in subdirectory:
        raise ExecutionException("'.' is not allowed in project subdirectory paths.")
    return parsed_uri, subdirectory


def _get_storage_dir(storage_dir):
    if storage_dir is not None and not os.path.exists(storage_dir):
        os.makedirs(storage_dir)
    return tempfile.mkdtemp(dir=storage_dir)


def _get_git_repo_url(work_dir):
    from git import Repo
    from git.exc import GitCommandError, InvalidGitRepositoryError

    try:
        repo = Repo(work_dir, search_parent_directories=True)
        remote_urls = [remote.url for remote in repo.remotes]
        if len(remote_urls) == 0:
            return None
    except GitCommandError:
        return None
    except InvalidGitRepositoryError:
        return None
    return remote_urls[0]


def _expand_uri(uri):
    if _is_local_uri(uri):
        return os.path.abspath(uri)
    return uri


def _is_wandb_uri(uri):
    return _WANDB_URI_REGEX.match(uri)


def _is_file_uri(uri):
    """Returns True if the passed-in URI is a file:// URI."""
    return _FILE_URI_REGEX.match(uri)


def _is_local_uri(uri):
    """Returns True if the passed-in URI should be interpreted as a path on the local filesystem."""
    return not _GIT_URI_REGEX.match(uri)


def _is_zip_uri(uri):
    """Returns True if the passed-in URI points to a ZIP file."""
    return _ZIP_URI_REGEX.match(uri)


def _is_valid_branch_name(work_dir, version):
    """
    Returns True if the ``version`` is the name of a branch in a Git project.
    ``work_dir`` must be the working directory in a git repo.
    """
    if version is not None:
        from git import Repo
        from git.exc import GitCommandError

        repo = Repo(work_dir, search_parent_directories=True)
        try:
            return repo.git.rev_parse("--verify", "refs/heads/%s" % version) != ""
        except GitCommandError:
            return False
    return False


def generate_docker_image(project_spec, version, entry_cmd, api):
    path = project_spec.dir
    cmd = ['jupyter-repo2docker',
            '--no-run',
            #'--no-build',
            # '--env', 'WANDB_API_KEY={}'.format(api.api_key),
            # '--user-name', 'root', # todo bad idea lol
            # '--debug',
            path,
            '"{}"'.format(entry_cmd),
            ]

    #if version:
    #    cmd.extend(['--ref', version])
    _logger.info('Generating docker image from git repo or finding image if it already exists..........')
    stderr = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.decode('utf-8')
    image_id = re.findall(r'Successfully tagged (.+):latest', stderr)
    if not image_id:
        image_id = re.findall(r'Reusing existing image \((.+)\)', stderr)
    if not image_id:
        raise Exception('error running repo2docker')
    return image_id[0]


def fetch_and_validate_project(uri, api, version, entry_point, parameters):
    parameters = parameters or {}
    work_dir = _fetch_project_local(uri=uri, api=api, version=version)
    project = _project_spec.load_project(work_dir)
    project.get_entry_point(entry_point)._validate_parameters(parameters)
    return project


def load_project(work_dir):
    return _project_spec.load_project(work_dir)


def fetch_wandb_project_run_info(uri, api=None):
    stripped_uri = re.sub(_WANDB_URI_REGEX, '', uri)
    entity, project, _, name = stripped_uri.split("/")[1:]
    result = api.get_run_info(entity, project, name)
    return result


def _fetch_project_local(uri, api, version=None):
    """
    Fetch a project into a local directory, returning the path to the local project directory.
    """
    parsed_uri, subdirectory = _parse_subdirectory(uri)
    use_temp_dst_dir = _is_zip_uri(parsed_uri) or not _is_local_uri(parsed_uri)
    dst_dir = tempfile.mkdtemp() if use_temp_dst_dir else parsed_uri
    if use_temp_dst_dir:
        _logger.info("=== Fetching project from %s into %s ===", uri, dst_dir)
    if _is_zip_uri(parsed_uri):
        if _is_file_uri(parsed_uri):
            parsed_file_uri = urllib.parse.urlparse(urllib.parse.unquote(parsed_uri))
            parsed_uri = os.path.join(parsed_file_uri.netloc, parsed_file_uri.path)
        _unzip_repo(
            zip_file=(
                parsed_uri if _is_local_uri(parsed_uri) else _fetch_zip_repo(parsed_uri)
            ),
            dst_dir=dst_dir,
        )
    elif _is_local_uri(uri):
        if version is not None:
            raise ExecutionException(
                "Setting a version is only supported for Git project URIs"
            )
        if use_temp_dst_dir:
            dir_util.copy_tree(src=parsed_uri, dst=dst_dir)
    elif _is_wandb_uri(uri):
        # TODO: so much hotness
        run_info = fetch_wandb_project_run_info(uri, api)
        if not run_info["git"]:
            raise ExecutionException("Run must have git repo associated")
        _fetch_git_repo(run_info["git"]["remote"], run_info["git"]["commit"], dst_dir)
        _create_ml_project_file_from_run_info(dst_dir, run_info)
    else:
        assert _GIT_URI_REGEX.match(parsed_uri), (
            "Non-local URI %s should be a Git URI" % parsed_uri
        )
        _fetch_git_repo(parsed_uri, version, dst_dir)
    res = os.path.abspath(os.path.join(dst_dir, subdirectory))
    if not os.path.exists(res):
        raise ExecutionException(
            "Could not find subdirectory %s of %s" % (subdirectory, dst_dir)
        )
    return res


def _create_ml_project_file_from_run_info(dst_dir, run_info):
    path = os.path.join(dst_dir, _project_spec.MLPROJECT_FILE_NAME)
    spec_keys_map = {
        "args": run_info["args"],
        "entrypoint": run_info["program"],
        "git": {"remote": run_info["git"]["remote"], "commit": run_info["git"]["commit"]},
        "python": run_info["python"],
        "os": run_info["os"]
    }
    with open(path, "w") as fp:
        yaml.dump(spec_keys_map, fp)


def _unzip_repo(zip_file, dst_dir):
    import zipfile

    with zipfile.ZipFile(zip_file) as zip_in:
        zip_in.extractall(dst_dir)


def _fetch_git_repo(uri, version, dst_dir):
    """
    Clone the git repo at ``uri`` into ``dst_dir``, checking out commit ``version`` (or defaulting
    to the head commit of the repository's master branch if version is unspecified).
    Assumes authentication parameters are specified by the environment, e.g. by a Git credential
    helper.
    """
    # We defer importing git until the last moment, because the import requires that the git
    # executable is available on the PATH, so we only want to fail if we actually need it.
    import git

    repo = git.Repo.init(dst_dir)
    origin = repo.create_remote("origin", uri)
    origin.fetch()
    if version is not None:
        try:
            repo.git.checkout(version)
        except git.exc.GitCommandError as e:
            raise ExecutionException(
                "Unable to checkout version '%s' of git repo %s"
                "- please ensure that the version exists in the repo. "
                "Error: %s" % (version, uri, e)
            )
    else:
        repo.create_head("master", origin.refs.master)
        repo.heads.master.checkout()
    repo.submodule_update(init=True, recursive=True)


def _fetch_zip_repo(uri):
    import requests
    from io import BytesIO

    response = requests.get(uri)
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise ExecutionException("Unable to retrieve ZIP file. Reason: %s" % str(error))
    return BytesIO(response.content)


def get_run_env_vars(run_id):
    """
    Returns a dictionary of environment variable key-value pairs to set in subprocess launched
    to run W&B projects.
    """
    #  TODO: pull vars from settings as well, set entity / project
    env_vars = {}
    # settings = wandb.Settings()
    if run_id:
        env_vars["WANDB_RUN_ID"] = run_id

    return env_vars


def get_entry_point_command(project, entry_point, parameters, storage_dir):
    """
    Returns the shell command to execute in order to run the specified entry point.
    :param project: Project containing the target entry point
    :param entry_point: Entry point to run
    :param parameters: Parameters (dictionary) for the entry point command
    :param storage_dir: Base local directory to use for downloading remote artifacts passed to
                        arguments of type 'path'. If None, a temporary base directory is used.
    """
    storage_dir_for_run = _get_storage_dir(storage_dir)
    _logger.info(
        "=== Created directory %s for downloading remote URIs passed to arguments of"
        " type 'path' ===",
        storage_dir_for_run,
    )
    commands = []
    commands.append(
        project.get_entry_point(entry_point).compute_command(
            parameters, storage_dir_for_run
        )
    )
    return commands


# Environment variable indicating a path to a conda installation. We will default to running
# "conda" if unset
WANDB_CONDA_HOME = "WANDB_CONDA_HOME"
_logger = logging.getLogger(__name__)


def get_conda_command(conda_env_name):
    #  Checking for newer conda versions
    if os.name != "nt" and (
        "CONDA_EXE" in os.environ or "WANDB_CONDA_HOME" in os.environ
    ):
        conda_path = get_conda_bin_executable("conda")
        activate_conda_env = [
            "source {}/../etc/profile.d/conda.sh".format(os.path.dirname(conda_path))
        ]
        activate_conda_env += ["conda activate {} 1>&2".format(conda_env_name)]
    else:
        activate_path = get_conda_bin_executable("activate")
        # in case os name is not 'nt', we are not running on windows. It introduces
        # bash command otherwise.
        if os.name != "nt":
            return ["source %s %s 1>&2" % (activate_path, conda_env_name)]
        else:
            return ["conda activate %s" % (conda_env_name)]
    return activate_conda_env


def get_conda_bin_executable(executable_name):
    """
    Return path to the specified executable, assumed to be discoverable within the 'bin'
    subdirectory of a conda installation.
    The conda home directory (expected to contain a 'bin' subdirectory) is configurable via the
    ``WANDB_CONDA_HOME`` environment variable. If it's is unspecified, this method simply returns the passed-in
    executable name.
    """
    conda_home = os.environ.get(WANDB_CONDA_HOME)
    if conda_home:
        return os.path.join(conda_home, "bin/%s" % executable_name)
    # Use CONDA_EXE as per https://github.com/conda/conda/issues/7126
    if "CONDA_EXE" in os.environ:
        conda_bin_dir = os.path.dirname(os.environ["CONDA_EXE"])
        return os.path.join(conda_bin_dir, executable_name)
    return executable_name


def _get_conda_env_name(conda_env_path, env_id=None):
    conda_env_contents = open(conda_env_path).read() if conda_env_path else ""
    if env_id:
        conda_env_contents += env_id
    return "wandb-%s" % hashlib.sha1(conda_env_contents.encode("utf-8")).hexdigest()


def get_or_create_conda_env(conda_env_path, env_id=None):
    """
    Given a `Project`, creates a conda environment containing the project's dependencies if such a
    conda environment doesn't already exist. Returns the name of the conda environment.
    :param conda_env_path: Path to a conda yaml file.
    :param env_id: Optional string that is added to the contents of the yaml file before
                   calculating the hash. It can be used to distinguish environments that have the
                   same conda dependencies but are supposed to be different based on the context.
                   For example, when serving the model we may install additional dependencies to the
                   environment after the environment has been activated.
    """
    conda_path = get_conda_bin_executable("conda")
    try:
        wandb.util.exec_cmd([conda_path, "--help"], throw_on_error=False)
    except EnvironmentError:
        raise ExecutionException(
            "Could not find Conda executable at {0}. "
            "Ensure Conda is installed as per the instructions at "
            "https://conda.io/projects/conda/en/latest/"
            "user-guide/install/index.html. "
            "You can also configure W&B to look for a specific "
            "Conda executable by setting the {1} environment variable "
            "to the path of the Conda executable".format(conda_path, WANDB_CONDA_HOME)
        )
    (_, stdout, _) = wandb.util.exec_cmd([conda_path, "env", "list", "--json"])
    env_names = [os.path.basename(env) for env in json.loads(stdout)["envs"]]
    project_env_name = _get_conda_env_name(conda_env_path, env_id)
    if project_env_name not in env_names:
        _logger.info("=== Creating conda environment %s ===", project_env_name)
        if conda_env_path:
            wandb.util.exec_cmd(
                [
                    conda_path,
                    "env",
                    "create",
                    "-n",
                    project_env_name,
                    "--file",
                    conda_env_path,
                ],
                stream_output=True,
            )
        else:
            wandb.util.exec_cmd(
                [conda_path, "create", "-n", project_env_name, "python"],
                stream_output=True,
            )
    return project_env_name
