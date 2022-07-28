# heavily inspired by https://github.com/mlflow/mlflow/blob/master/mlflow/projects/utils.py
import logging
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import wandb
from wandb import util
from wandb.apis.internal import Api
from wandb.errors import CommError, ExecutionError, LaunchError

if TYPE_CHECKING:  # pragma: no cover
    from wandb.apis.public import Artifact as PublicArtifact


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(r"^[^/|^~|^\.].*(git|bitbucket)")
_VALID_IP_REGEX = r"^https?://[0-9]+(?:\.[0-9]+){3}(:[0-9]+)?"
_VALID_PIP_PACKAGE_REGEX = r"^[a-zA-Z0-9_.-]+$"
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
LAUNCH_CONFIG_FILE = "~/.config/wandb/launch-config.yaml"


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
    job: Optional[str],
    api: Api,
    name: Optional[str],
    project: Optional[str],
    entity: Optional[str],
    docker_image: Optional[str],
    resource: Optional[str],
    entry_point: Optional[List[str]],
    version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    resource_args: Optional[Dict[str, Any]],
    launch_config: Optional[Dict[str, Any]],
    cuda: Optional[bool],
    run_id: Optional[str],
) -> Dict[str, Any]:
    """Constructs the launch specification from CLI arguments."""
    # override base config (if supplied) with supplied args
    launch_spec = launch_config if launch_config is not None else {}
    if uri is not None:
        launch_spec["uri"] = uri
    if job is not None:
        launch_spec["job"] = job
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

    if run_id is not None:
        launch_spec["run_id"] = run_id

    return launch_spec


def validate_launch_spec_source(launch_spec: Dict[str, Any]) -> None:
    uri = launch_spec.get("uri")
    job = launch_spec.get("job")
    docker_image = launch_spec.get("docker", {}).get("docker_image")

    if not bool(uri) and not bool(job) and not bool(docker_image):
        raise LaunchError("Must specify a uri, job or docker image")
    elif sum(map(bool, [uri, job, docker_image])) > 1:
        raise LaunchError("Must specify exactly one of uri, job or image")


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
    try:
        entity, project, _, name = stripped_uri.split("/")[1:]
    except ValueError as e:
        raise LaunchError(f"Trouble parsing wandb uri {uri}: {e}")
    return entity, project, name


def is_bare_wandb_uri(uri: str) -> bool:
    """Checks if the uri is of the format /entity/project/runs/run_name"""
    _logger.info(f"Checking if uri {uri} is bare...")
    if not uri.startswith("/"):
        return False
    result = uri.split("/")[1:]
    # a bare wandb uri will have 4 parts, with the last being the run name
    # and the second last being "runs"
    if len(result) == 4 and result[-2] == "runs":
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


def get_local_python_deps(
    dir: str, filename: str = "requirements.local.txt"
) -> Optional[str]:
    try:
        env = os.environ
        with open(os.path.join(dir, filename), "w") as f:
            subprocess.call(["pip", "freeze"], env=env, stdout=f)
        return filename
    except subprocess.CalledProcessError as e:
        wandb.termerror(f"Command failed: {e}")
        return None


def diff_pip_requirements(req_1: List[str], req_2: List[str]) -> Dict[str, str]:
    """Returns a list of pip requirements that are not in req_1 but are in req_2."""

    def _parse_req(req: List[str]) -> Dict[str, str]:
        # TODO: This can be made more exhaustive, but for 99% of cases this is fine
        # see https://pip.pypa.io/en/stable/reference/requirements-file-format/#example
        d: Dict[str, str] = dict()
        for line in req:
            _name: str = None  # type: ignore
            _version: str = None  # type: ignore
            if line.startswith("#"):  # Ignore comments
                continue
            elif "git+" in line or "hg+" in line:
                _name = line.split("#egg=")[1]
                _version = line.split("@")[-1].split("#")[0]
            elif "==" in line:
                _s = line.split("==")
                _name = _s[0].lower()
                _version = _s[1].split("#")[0].strip()
            elif ">=" in line:
                _s = line.split(">=")
                _name = _s[0].lower()
                _version = _s[1].split("#")[0].strip()
            elif ">" in line:
                _s = line.split(">")
                _name = _s[0].lower()
                _version = _s[1].split("#")[0].strip()
            elif re.match(_VALID_PIP_PACKAGE_REGEX, line) is not None:
                _name = line
            else:
                raise ValueError(f"Unable to parse pip requirements file line: {line}")
            if _name is not None:
                assert re.match(
                    _VALID_PIP_PACKAGE_REGEX, _name
                ), f"Invalid pip package name {_name}"
                d[_name] = _version
        return d

    # Use symmetric difference between dict representation to print errors
    try:
        req_1_dict: Dict[str, str] = _parse_req(req_1)
        req_2_dict: Dict[str, str] = _parse_req(req_2)
    except (AssertionError, ValueError, IndexError, KeyError) as e:
        raise LaunchError(f"Failed to parse pip requirements: {e}")
    diff: List[Tuple[str, str]] = []
    for item in set(req_1_dict.items()) ^ set(req_2_dict.items()):
        diff.append(item)
    # Parse through the diff to make it pretty
    pretty_diff: Dict[str, str] = {}
    for name, version in diff:
        if pretty_diff.get(name) is None:
            pretty_diff[name] = version
        else:
            pretty_diff[name] = f"v{version} and v{pretty_diff[name]}"
    return pretty_diff


def validate_wandb_python_deps(
    requirements_file: Optional[str],
    dir: str,
) -> None:
    """Warns if local python dependencies differ from wandb requirements.txt"""
    if requirements_file is not None:
        requirements_path = os.path.join(dir, requirements_file)
        with open(requirements_path) as f:
            wandb_python_deps: List[str] = f.read().splitlines()

        local_python_file = get_local_python_deps(dir)
        if local_python_file is not None:
            local_python_deps_path = os.path.join(dir, local_python_file)
            with open(local_python_deps_path) as f:
                local_python_deps: List[str] = f.read().splitlines()

            diff_pip_requirements(wandb_python_deps, local_python_deps)
            return
    _logger.warning("Unable to validate local python dependencies")


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
) -> Optional["PublicArtifact"]:
    _logger.info("Checking for code artifacts")
    public_api = wandb.PublicApi(
        overrides={"base_url": internal_api.settings("base_url")}
    )

    run = public_api.run(f"{entity}/{project}/{run_name}")
    run_artifacts = run.logged_artifacts()

    for artifact in run_artifacts:
        if hasattr(artifact, "type") and artifact.type == "code":
            artifact.download(project_dir)
            return artifact  # type: ignore

    return None


def to_camel_case(maybe_snake_str: str) -> str:
    if "_" not in maybe_snake_str:
        return maybe_snake_str
    components = maybe_snake_str.split("_")
    return "".join(x.title() if x else "_" for x in components)


def run_shell(args: List[str]) -> Tuple[str, str]:
    out = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out.stdout.decode("utf-8").strip(), out.stderr.decode("utf-8").strip()


def validate_build_and_registry_configs(
    build_config: Dict[str, Any], registry_config: Dict[str, Any]
) -> None:
    build_config_credentials = build_config.get("credentials", {})
    registry_config_credentials = registry_config.get("credentials", {})
    if (
        build_config_credentials
        and registry_config_credentials
        and build_config_credentials != registry_config_credentials
    ):
        raise LaunchError("registry and build config credential mismatch")


def get_kube_context_and_api_client(
    kubernetes: Any,  # noqa: F811
    resource_args: Dict[str, Any],  # noqa: F811
) -> Tuple[Any, Any]:

    config_file = resource_args.get("config_file", None)
    context = None
    if config_file is not None or os.path.exists(os.path.expanduser("~/.kube/config")):
        # context only exist in the non-incluster case

        all_contexts, active_context = kubernetes.config.list_kube_config_contexts(
            config_file
        )
        context = None
        if resource_args.get("context"):
            context_name = resource_args["context"]
            for c in all_contexts:
                if c["name"] == context_name:
                    context = c
                    break
            raise LaunchError(f"Specified context {context_name} was not found.")
        else:
            context = active_context

        kubernetes.config.load_kube_config(config_file, context["name"])
        api_client = kubernetes.config.new_client_from_config(
            config_file, context=context["name"]
        )
        return context, api_client
    else:
        kubernetes.config.load_incluster_config()
        api_client = kubernetes.client.api_client.ApiClient()
        return context, api_client


def resolve_build_and_registry_config(
    default_launch_config: Optional[Dict[str, Any]],
    build_config: Optional[Dict[str, Any]],
    registry_config: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    resolved_build_config: Dict[str, Any] = {}
    if build_config is None and default_launch_config is not None:
        resolved_build_config = default_launch_config.get("build", {})
    elif build_config is not None:
        resolved_build_config = build_config
    resolved_registry_config: Dict[str, Any] = {}
    if registry_config is None and default_launch_config is not None:
        resolved_registry_config = default_launch_config.get("registry", {})
    elif registry_config is not None:
        resolved_registry_config = registry_config
    validate_build_and_registry_configs(resolved_build_config, resolved_registry_config)
    return resolved_build_config, resolved_registry_config
