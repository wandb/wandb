# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import hashlib
import json
import logging
import os
import subprocess
import re
import tempfile
import yaml
from gql import Client, gql
from gql.client import RetryError  # type: ignore
from gql.transport.requests import RequestsHTTPTransport  # type: ignore
import wandb
from wandb.errors import ExecutionException
import time
from ._project_spec import Project, MLPROJECT_FILE_NAME


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/]*:")
_FILE_URI_REGEX = re.compile(r"^file://.+")
_ZIP_URI_REGEX = re.compile(r".+\.zip$")
_WANDB_URI_REGEX = re.compile(r"^https://wandb")
_WANDB_DEV_URI_REGEX = re.compile(r"^https?://ap\w.wandb")   # for testing, not sure if we wanna keep this

WANDB_DOCKER_WORKDIR_PATH = "/wandb/projects/code/"

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
    return _WANDB_URI_REGEX.match(uri) or _WANDB_DEV_URI_REGEX.match(uri)


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
    # Is this needed here, version refers to the github commit
    # if version:
    #    cmd.extend(['--ref', version])
    _logger.info('Generating docker image from git repo or finding image if it already exists..........')
    stderr = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.decode('utf-8')
    image_id = re.findall(r'Successfully tagged (.+):latest', stderr)
    if not image_id:
        image_id = re.findall(r'Reusing existing image \((.+)\)', stderr)
    if not image_id:
        raise Exception('error running repo2docker')
    return image_id[0]


def fetch_and_validate_project(uri, api, runner_name, version, entry_point, parameters):
    parameters = parameters or {}

    # todo: we maybe don't always want to dl project to local
    project = Project(uri, "name", version, [entry_point], parameters)
    project._fetch_project_local(api=api, version=version)
    project.get_entry_point(entry_point)._validate_parameters(parameters)
    return project


def fetch_wandb_project_run_info(uri, api=None):
    stripped_uri = re.sub(_WANDB_URI_REGEX, '', uri)
    stripped_uri = re.sub(_WANDB_DEV_URI_REGEX, '', stripped_uri)    # also for testing just run it twice
    entity, project, _, name = stripped_uri.split("/")[1:]
    result = api.get_run_info(entity, project, name)
    return result


def _create_ml_project_file_from_run_info(dst_dir, run_info):
    path = os.path.join(dst_dir, MLPROJECT_FILE_NAME)
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
        env_vars["WANDB_RUN_ID"] = run_id       # @@@ fix this

    return env_vars         # @@@ todo this fn currently doesn't do anything


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
        entry_point.compute_command(
            parameters, storage_dir_for_run
        )
    )
    return commands

