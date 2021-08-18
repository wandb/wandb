# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import logging
import os
import re
import subprocess
from typing import Any, Dict, Optional, Tuple

import wandb
from wandb import util
from wandb.apis.internal import Api
from wandb.errors import CommError, ExecutionError, LaunchError


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/|^~|^\.].*(git|bitbucket)")
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


def _is_wandb_uri(uri: str) -> bool:
    return (
        _WANDB_URI_REGEX.match(uri)
        or _WANDB_DEV_URI_REGEX.match(uri)
        or _WANDB_LOCAL_DEV_URI_REGEX.match(uri)
        or _WANDB_QA_URI_REGEX.match(uri)
    ) is not None


def _is_wandb_dev_uri(uri: str) -> bool:
    return bool(_WANDB_DEV_URI_REGEX.match(uri))


def _is_wandb_local_uri(uri: str) -> bool:
    return bool(_WANDB_LOCAL_DEV_URI_REGEX.match(uri))


def _is_git_uri(uri: str) -> bool:
    return bool(_GIT_URI_REGEX.match(uri))


def set_project_entity_defaults(
    uri: str,
    api: Api,
    project: Optional[str],
    entity: Optional[str],
    launch_config: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    # set the target project and entity if not provided
    if _is_wandb_uri(uri):
        _, uri_project, _ = parse_wandb_uri(uri)
    elif _is_git_uri(uri):
        uri_project = os.path.splitext(os.path.basename(uri))[0]
    else:
        uri_project = UNCATEGORIZED_PROJECT
    if project is None:
        config_project = None
        if launch_config:
            config_project = launch_config.get("project")
        project = config_project or uri_project or UNCATEGORIZED_PROJECT
        wandb.termlog(
            "Target project for this run not specified, defaulting to project {}".format(
                project
            )
        )
    if entity is None:
        config_entity = None
        if launch_config:
            config_entity = launch_config.get("entity")
        entity = config_entity or api.default_entity
        wandb.termlog(
            "Target entity for this run not specified, defaulting to current logged-in user {}".format(
                entity
            )
        )
    return project, entity


def construct_launch_spec(
    uri: str,
    api: Api,
    name: Optional[str],
    project: Optional[str],
    entity: Optional[str],
    docker_image: Optional[str],
    entry_point: Optional[str],
    version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    launch_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Constructs the launch specification from CLI arguments."""
    # override base config (if supplied) with supplied args
    launch_spec = launch_config if launch_config is not None else {}
    launch_spec["uri"] = uri
    project, entity = set_project_entity_defaults(
        uri, api, project, entity, launch_config,
    )
    launch_spec["entity"] = entity

    launch_spec["project"] = project
    if name:
        launch_spec["name"] = name
    if "docker" not in launch_spec:
        launch_spec["docker"] = {}
    if docker_image:
        launch_spec["docker"]["docker_image"] = docker_image

    if "git" not in launch_spec:
        launch_spec["git"] = {}
    if version:
        launch_spec["git"]["version"] = version

    if "overrides" not in launch_spec:
        launch_spec["overrides"] = {}

    if parameters:
        override_args = util._user_args_to_dict(
            launch_spec["overrides"].get("args", [])
        )
        if isinstance(override_args, list):
            base_args = util._user_args_to_dict(
                launch_spec["overrides"].get("args", [])
            )
        elif isinstance(override_args, dict):
            base_args = override_args
        launch_spec["overrides"]["args"] = merge_parameters(parameters, base_args)
    elif isinstance(launch_spec["overrides"].get("args"), list):
        launch_spec["overrides"]["args"] = util._user_args_to_dict(
            launch_spec["overrides"].get("args")
        )
    if entry_point:
        launch_spec["overrides"]["entry_point"] = entry_point

    return launch_spec


def parse_wandb_uri(uri: str) -> Tuple[str, str, str]:
    """Parses wandb uri to retrieve entity, project and run name."""
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


def fetch_wandb_project_run_info(uri: str, api: Api) -> Any:
    """Fetches wandb run info."""
    entity, project, name = parse_wandb_uri(uri)
    try:
        result = api.get_run_info(entity, project, name)
    except CommError as e:
        raise LaunchError(e)
    if result is None:
        raise LaunchError("Run info is invalid or doesn't exist for {}".format(uri))
    if result.get("args") is not None:
        result["args"] = util._user_args_to_dict(result["args"])
    return result


def fetch_project_diff(uri: str, api: Api) -> Optional[str]:
    """Fetches project diff from wandb servers."""
    patch = None
    try:
        entity, project, name = parse_wandb_uri(uri)
        (_, _, patch, _) = api.run_config(project, name, entity)
    except CommError:
        pass
    return patch


def apply_patch(patch_string: str, dst_dir: str) -> None:
    """Applies a patch file to a directory."""
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


def _fetch_git_repo(dst_dir: str, uri: str, version: Optional[str]) -> None:
    """Clones the git repo at ``uri`` into ``dst_dir``.

    checks out commit ``version`` (or defaults to the head commit of the repository's
    master branch if version is unspecified). Assumes authentication parameters are
    specified by the environment, e.g. by a Git credential helper.
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
            raise ExecutionError(
                "Unable to checkout version '%s' of git repo %s"
                "- please ensure that the version exists in the repo. "
                "Error: %s" % (version, uri, e)
            )
    else:
        repo.create_head("master", origin.refs.master)
        repo.heads.master.checkout()
    repo.submodule_update(init=True, recursive=True)


def merge_parameters(
    higher_priority_params: Dict[str, Any], lower_priority_params: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge the contents of two dicts, keeping values from higher_priority_params if there are conflicts."""
    return {**lower_priority_params, **higher_priority_params}
