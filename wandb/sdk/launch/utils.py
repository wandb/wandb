# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import logging
import os
import re
import subprocess

import wandb
from wandb.errors import CommError, ExecutionException, LaunchException
from wandb import util

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


PROJECT_SYNCHRONOUS = "SYNCHRONOUS"
PROJECT_DOCKER_ARGS = "DOCKER_ARGS"

UNCATEGORIZED_PROJECT = "uncategorized"


_logger = logging.getLogger(__name__)


def _is_wandb_uri(uri: str):
    return (
        _WANDB_URI_REGEX.match(uri)
        or _WANDB_DEV_URI_REGEX.match(uri)
        or _WANDB_LOCAL_DEV_URI_REGEX.match(uri)
        or _WANDB_QA_URI_REGEX.match(uri)
    )


def _is_wandb_dev_uri(uri: str):
    return _WANDB_DEV_URI_REGEX.match(uri)


def _is_wandb_local_uri(uri: str):
    return _WANDB_LOCAL_DEV_URI_REGEX.match(uri)


def set_project_entity_defaults(uri, project, entity, api):
    # set the target project and entity if not provided
    if not _is_wandb_uri(uri):
        wandb.termlog("Non-wandb path detected")
    _, uri_project, run_id = parse_wandb_uri(uri)
    if project is None:
        project = api.settings("project") or uri_project or UNCATEGORIZED_PROJECT
    if entity is None:
        entity = api.default_entity
    return project, entity, run_id


def construct_run_spec(
    uri,
    experiment_name,
    wandb_project,
    wandb_entity,
    docker_image,
    entry_point,
    version,
    parameters,
    launch_config,
):
    # override base config (if supplied) with supplied args
    run_spec = launch_config if launch_config is not None else {}
    run_spec["uri"] = uri
    run_spec["entity"] = wandb_entity
    run_spec["project"] = wandb_project
    run_spec["name"] = experiment_name
    if "docker" not in run_spec:
        run_spec["docker"] = {}
    if docker_image:
        run_spec["docker"]["docker_image"] = docker_image

    if "git" not in run_spec:
        run_spec["git"] = {}
    if version:
        run_spec["git"]["version"] = version

    if "overrides" not in run_spec:
        run_spec["overrides"] = {}
    if parameters:
        base_args = util._user_args_to_dict(run_spec["overrides"].get("args", []))
        run_spec["overrides"]["args"] = merge_parameters(parameters, base_args)
    if entry_point:
        run_spec["overrides"]["entry_point"] = entry_point

    return run_spec


def create_project_from_spec(run_spec, api):
    uri = run_spec["uri"]
    project, entity, run_id = set_project_entity_defaults(uri, run_spec.get("project"), run_spec.get("entity"), api)
    if run_spec.get("name"):
        name = run_spec["name"]
    else:
        name = "{}_{}_launch".format(project, run_id)   # default naming scheme    

    return _project_spec.Project(
        uri,
        entity,
        project,
        name,
        run_spec.get("docker", {}),
        run_spec.get("git", {}),
        run_spec.get("overrides", {}),
    )


def fetch_and_validate_project(project, api):
    project._fetch_project_local(api=api)
    project._copy_config_local()
    first_entry_point = list(project._entry_points.keys())[0]
    project.get_entry_point(first_entry_point)._validate_parameters(project.override_args)     # todo:steph useless validation
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
    if result.get("args") is not None:
        result["args"] = util._user_args_to_dict(result["args"])
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


def merge_parameters(higher_priority_params, lower_priority_params):
    for key in lower_priority_params.keys():
        if higher_priority_params.get(key) is None:
            higher_priority_params[key] = lower_priority_params[key]
    return higher_priority_params
