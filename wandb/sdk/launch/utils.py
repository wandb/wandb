# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import logging
import os
import re
import subprocess

import wandb
from wandb.errors import CommError, ExecutionException, LaunchException

from . import _project_spec


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/]*:")
_WANDB_URI_REGEX = re.compile(r"^https://(api.)?wandb")
_WANDB_QA_URI_REGEX = re.compile(
    r"^https?://ap\w.qa.wandb"
)  # for testing, not sure if we wanna keep this
_WANDB_DEV_URI_REGEX = re.compile(
    r"^https?://ap\w.wandb.test"
)  # for testing, not sure if we wanna keep this
_WANDB_LOCAL_DEV_URI_REGEX = re.compile(
    r"^https?://localhost"
)  # for testing, not sure if we wanna keep this

WANDB_DOCKER_WORKDIR_PATH = "/wandb/projects/code/"

PROJECT_SYNCHRONOUS = "SYNCHRONOUS"
PROJECT_DOCKER_ARGS = "DOCKER_ARGS"

UNCATEGORIZED_PROJECT = "uncategorized"


_logger = logging.getLogger(__name__)


def _is_wandb_uri(uri):
    return (
        _WANDB_URI_REGEX.match(uri)
        or _WANDB_DEV_URI_REGEX.match(uri)
        or _WANDB_LOCAL_DEV_URI_REGEX.match(uri)
        or _WANDB_QA_URI_REGEX.match(uri)
    )


def _is_wandb_dev_uri(uri):
    return _WANDB_DEV_URI_REGEX.match(uri)


def _is_wandb_local_uri(uri):
    return _WANDB_LOCAL_DEV_URI_REGEX.match(uri)


def _is_local_uri(uri):
    """Returns True if the passed-in URI should be interpreted as a path on the local filesystem."""
    return not _GIT_URI_REGEX.match(uri)


def _collect_args(args):
    dict_args = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if "=" in arg:
            name, vals = arg.split("=")
            dict_args[name.lstrip("-")] = vals
            i += 1
        elif (
            arg.startswith("-")
            and i < len(args) - 1
            and not args[i + 1].startswith("-")
        ):
            dict_args[arg.lstrip("-")] = args[i + 1]
            i += 2
        else:
            dict_args[arg.lstrip("-")] = None
            i += 1
    return dict_args


def fetch_and_validate_project(
    uri,
    target_entity,
    target_project,
    experiment_name,
    api,
    version,
    entry_point,
    parameters,
    run_config,
):
    parameters = parameters or {}
    experiment_name = experiment_name
    project = _project_spec.Project(
        uri,
        target_entity,
        target_project,
        experiment_name,
        version,
        [entry_point],
        parameters,
        run_config,
    )
    # todo: we maybe don't always want to dl project to local
    project._fetch_project_local(api=api, version=version)
    project._copy_config_local()
    first_entry_point = list(project._entry_points.keys())[0]
    project.get_entry_point(first_entry_point)._validate_parameters(parameters)
    return project


def parse_wandb_uri(uri):
    uri = uri.split("?")[0]  # remove any possible query params (eg workspace)
    stripped_uri = re.sub(_WANDB_URI_REGEX, "", uri)
    stripped_uri = re.sub(
        _WANDB_DEV_URI_REGEX, "", stripped_uri
    )  # also for testing just run it twice
    stripped_uri = re.sub(
        _WANDB_LOCAL_DEV_URI_REGEX, "", stripped_uri
    )  # also for testing just run it twice
    stripped_uri = re.sub(
        _WANDB_QA_URI_REGEX, "", stripped_uri
    )  # also for testing just run it twice
    entity, project, _, name = stripped_uri.split("/")[1:]
    return entity, project, name


def fetch_wandb_project_run_info(uri, api=None):
    entity, project, name = parse_wandb_uri(uri)
    result = api.get_run_info(entity, project, name)
    if result is None:
        raise LaunchException("Run info is invalid or doesn't exist for {}".format(uri))
    return result


def fetch_project_diff(uri, api=None):
    patch = None
    try:
        entity, project, name = parse_wandb_uri(uri)
        (_, _, patch, _) = api.run_config(project, name, entity)
    except CommError:
        pass
    return patch


def set_project_entity_defaults(uri, project, entity, api):
    if not _is_wandb_uri(uri):
        raise LaunchException("Non-wandb URLs not yet supported in this feature")
    _, uri_project, run_id = parse_wandb_uri(uri)
    if project is None:
        project = api.settings("project") or uri_project or UNCATEGORIZED_PROJECT
    if entity is None:
        entity = api.default_entity
    return project, entity, run_id


def apply_patch(patch_string, dst_dir):
    with open(os.path.join(dst_dir, "diff.patch"), "w") as fp:
        fp.write(patch_string)
    try:
        subprocess.check_call(
            [
                "patch",
                "-s",
                "--directory={}".format(dst_dir),
                "-p1",
                "-i",
                "diff.patch",
            ]
        )
    except subprocess.CalledProcessError:
        raise wandb.Error("Failed to apply diff.patch associated with run.")


def _fetch_git_repo(uri, version, dst_dir):
    """
    Clone the git repo at ``uri`` into ``dst_dir``, checking out commit ``version`` (or defaulting
    to the head commit of the repository's master branch if version is unspecified).
    Assumes authentication parameters are specified by the environment, e.g. by a Git credential
    helper.
    """
    # We defer importing git until the last moment, because the import requires that the git
    # executable is available on the PATH, so we only want to fail if we actually need it.
    import git  # type: ignore

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


def get_entry_point_command(project, entry_point, parameters):
    """
    Returns the shell command to execute in order to run the specified entry point.
    :param project: Project containing the target entry point
    :param entry_point: Entry point to run
    :param parameters: Parameters (dictionary) for the entry point command
    """
    commands = []
    commands.append(entry_point.compute_command(parameters))
    return commands


def _convert_access(access):
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


def merge_parameters(higher_priority_params, lower_priority_params):
    for key in lower_priority_params.keys():
        if higher_priority_params.get(key) is None:
            higher_priority_params[key] = lower_priority_params[key]
    return higher_priority_params
