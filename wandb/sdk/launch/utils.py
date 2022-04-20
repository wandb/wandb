# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import logging
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb import util
from wandb.apis.internal import Api
from wandb.errors import CommError, ExecutionError, LaunchError


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/|^~|^\.].*(git|bitbucket)")
_VALID_IP_REGEX = r"^https?://[0-9]+(?:\.[0-9]+){3}(:[0-9]+)?"
_VALID_WANDB_REGEX = r"^https?://(api.)?wandb"
_WANDB_URI_REGEX = re.compile(r"|".join([_VALID_WANDB_REGEX, _VALID_IP_REGEX]))
_WANDB_QA_URI_REGEX = re.compile(
    r"^https?://ap\w.qa.wandb"
)  # for testing, not sure if we wanna keep this
_WANDB_DEV_URI_REGEX = re.compile(
    r"^https?://ap\w.wandb.test"
)  # for testing, not sure if we wanna keep this
_WANDB_LOCAL_DEV_URI_REGEX = re.compile(
    r"^https?://localhost"
)  # for testing, not sure if we wanna keep this

API_KEY_REGEX = r"WANDB_API_KEY=\w+"

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


def sanitize_wandb_api_key(s: str) -> str:
    return str(re.sub(API_KEY_REGEX, "WANDB_API_KEY", s))


def set_project_entity_defaults(
    uri: Optional[str],
    api: Api,
    project: Optional[str],
    entity: Optional[str],
    launch_config: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    # set the target project and entity if not provided
    if uri is not None:
        if _is_wandb_uri(uri):
            _, uri_project, _ = parse_wandb_uri(uri)
        elif _is_git_uri(uri):
            uri_project = os.path.splitext(os.path.basename(uri))[0]
        else:
            uri_project = UNCATEGORIZED_PROJECT
    else:
        uri_project = UNCATEGORIZED_PROJECT
    if project is None:
        config_project = None
        if launch_config:
            config_project = launch_config.get("project")
        project = config_project or uri_project or UNCATEGORIZED_PROJECT
    if entity is None:
        config_entity = None
        if launch_config:
            config_entity = launch_config.get("entity")
        entity = config_entity or api.default_entity
    prefix = ""
    if platform.system() != "Windows" and sys.stdout.encoding == "UTF-8":
        prefix = "🚀 "
    wandb.termlog(f"{prefix}Launching run into {entity}/{project}")
    return project, entity


def construct_launch_spec(
    uri: Optional[str],
    api: Api,
    name: Optional[str],
    project: Optional[str],
    entity: Optional[str],
    docker_image: Optional[str],
    resource: Optional[str],
    entry_point: Optional[str],
    version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    resource_args: Optional[Dict[str, Any]],
    launch_config: Optional[Dict[str, Any]],
    cuda: Optional[bool],
) -> Dict[str, Any]:
    """Constructs the launch specification from CLI arguments."""
    # override base config (if supplied) with supplied args
    launch_spec = launch_config if launch_config is not None else {}
    if uri is not None:
        launch_spec["uri"] = uri
    project, entity = set_project_entity_defaults(
        uri,
        api,
        project,
        entity,
        launch_config,
    )
    launch_spec["entity"] = entity

    launch_spec["project"] = project
    if name:
        launch_spec["name"] = name
    if "docker" not in launch_spec:
        launch_spec["docker"] = {}
    if docker_image:
        launch_spec["docker"]["docker_image"] = docker_image

    if "resource" not in launch_spec:
        launch_spec["resource"] = resource or "local"

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
        base_args = override_args
        launch_spec["overrides"]["args"] = merge_parameters(parameters, base_args)
    elif isinstance(launch_spec["overrides"].get("args"), list):
        launch_spec["overrides"]["args"] = util._user_args_to_dict(
            launch_spec["overrides"].get("args")
        )

    if resource_args:
        launch_spec["resource_args"] = resource_args

    if entry_point:
        launch_spec["overrides"]["entry_point"] = entry_point
    if cuda is not None:
        launch_spec["cuda"] = cuda

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


def is_bare_wandb_uri(uri: str) -> bool:
    """Checks if the uri is of the format /entity/project/runs/run_name"""
    _logger.info(f"Checking if uri {uri} is bare...")
    if not uri.startswith("/"):
        return False
    result = uri.split("/")[1:]
    # a bare wandb uri will have 4 parts, with the last being the run name
    # and the second last being "runs"
    if len(result) == 4 and result[-2] == "runs" and len(result[-1]) == 8:
        return True
    return False


def fetch_wandb_project_run_info(
    entity: str, project: str, run_name: str, api: Api
) -> Any:
    _logger.info("Fetching run info...")
    try:
        result = api.get_run_info(entity, project, run_name)
    except CommError:
        result = None
    if result is None:
        raise LaunchError(
            f"Run info is invalid or doesn't exist for {api.settings('base_url')}/{entity}/{project}/runs/{run_name}"
        )
    if result.get("codePath") is None:
        # TODO: we don't currently expose codePath in the runInfo endpoint, this downloads
        # it from wandb-metadata.json if we can.
        metadata = api.download_url(
            project, "wandb-metadata.json", run=run_name, entity=entity
        )
        if metadata is not None:
            _, response = api.download_file(metadata["url"])
            data = response.json()
            result["codePath"] = data.get("codePath")
            result["cudaVersion"] = data.get("cuda", None)

    if result.get("args") is not None:
        result["args"] = util._user_args_to_dict(result["args"])
    return result


def download_entry_point(
    entity: str, project: str, run_name: str, api: Api, entry_point: str, dir: str
) -> bool:
    metadata = api.download_url(
        project, f"code/{entry_point}", run=run_name, entity=entity
    )
    if metadata is not None:
        _, response = api.download_file(metadata["url"])
        with util.fsync_open(os.path.join(dir, entry_point), "wb") as file:
            for data in response.iter_content(chunk_size=1024):
                file.write(data)
        return True
    return False


def download_wandb_python_deps(
    entity: str, project: str, run_name: str, api: Api, dir: str
) -> Optional[str]:
    reqs = api.download_url(project, "requirements.txt", run=run_name, entity=entity)
    if reqs is not None:
        _logger.info("Downloading python dependencies")
        _, response = api.download_file(reqs["url"])

        with util.fsync_open(
            os.path.join(dir, "requirements.frozen.txt"), "wb"
        ) as file:
            for data in response.iter_content(chunk_size=1024):
                file.write(data)
        return "requirements.frozen.txt"
    return None


def fetch_project_diff(
    entity: str, project: str, run_name: str, api: Api
) -> Optional[str]:
    """Fetches project diff from wandb servers."""
    _logger.info("Searching for diff.patch")
    patch = None
    try:
        (_, _, patch, _) = api.run_config(project, run_name, entity)
    except CommError:
        pass
    return patch


def apply_patch(patch_string: str, dst_dir: str) -> None:
    """Applies a patch file to a directory."""
    _logger.info("Applying diff.patch")
    with open(os.path.join(dst_dir, "diff.patch"), "w") as fp:
        fp.write(patch_string)
    try:
        subprocess.check_call(
            [
                "patch",
                "-s",
                f"--directory={dst_dir}",
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

    _logger.info("Fetching git repo")
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


def convert_jupyter_notebook_to_script(fname: str, project_dir: str) -> str:
    nbconvert = wandb.util.get_module(
        "nbconvert", "nbformat and nbconvert are required to use launch with notebooks"
    )
    nbformat = wandb.util.get_module(
        "nbformat", "nbformat and nbconvert are required to use launch with notebooks"
    )

    _logger.info("Converting notebook to script")
    new_name = fname.rstrip(".ipynb") + ".py"
    with open(os.path.join(project_dir, fname)) as fh:
        nb = nbformat.reads(fh.read(), nbformat.NO_CONVERT)

    exporter = nbconvert.PythonExporter()
    source, meta = exporter.from_notebook_node(nb)

    with open(os.path.join(project_dir, new_name), "w+") as fh:
        fh.writelines(source)
    return new_name


def check_and_download_code_artifacts(
    entity: str, project: str, run_name: str, internal_api: Api, project_dir: str
) -> bool:
    _logger.info("Checking for code artifacts")
    public_api = wandb.PublicApi(
        overrides={"base_url": internal_api.settings("base_url")}
    )

    run = public_api.run(f"{entity}/{project}/{run_name}")
    run_artifacts = run.logged_artifacts()

    for artifact in run_artifacts:
        if hasattr(artifact, "type") and artifact.type == "code":
            artifact.download(project_dir)
            return True

    return False


def to_camel_case(maybe_snake_str: str) -> str:
    if "_" not in maybe_snake_str:
        return maybe_snake_str
    components = maybe_snake_str.split("_")
    return "".join(x.title() if x else "_" for x in components)


def run_shell(args: List[str]) -> Tuple[str, str]:
    out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out.stdout.decode("utf-8").strip(), out.stderr.decode("utf-8").strip()
