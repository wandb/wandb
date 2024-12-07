import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

import click

import wandb
import wandb.docker as docker
from wandb import util
from wandb.apis.internal import Api
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.git_reference import GitReference
from wandb.sdk.launch.wandb_reference import WandbReference
from wandb.sdk.wandb_config import Config

from .builder.templates._wandb_bootstrap import (
    FAILED_PACKAGES_POSTFIX,
    FAILED_PACKAGES_PREFIX,
)

FAILED_PACKAGES_REGEX = re.compile(
    f"{re.escape(FAILED_PACKAGES_PREFIX)}(.*){re.escape(FAILED_PACKAGES_POSTFIX)}"
)

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker


# TODO: this should be restricted to just Git repos and not S3 and stuff like that
_GIT_URI_REGEX = re.compile(
    r"^[^/|^~|^\.].*(git|bitbucket|dev\.azure\.com|\.visualstudio\.com)"
)
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

API_KEY_REGEX = r"WANDB_API_KEY=\w+(-\w+)?"

MACRO_REGEX = re.compile(r"\$\{(\w+)\}")

AZURE_CONTAINER_REGISTRY_URI_REGEX = re.compile(
    r"^(?:https://)?([\w]+)\.azurecr\.io/(?P<repository>[\w\-]+):?(?P<tag>.*)"
)

ELASTIC_CONTAINER_REGISTRY_URI_REGEX = re.compile(
    r"^(?:https://)?(?P<account>[\w-]+)\.dkr\.ecr\.(?P<region>[\w-]+)\.amazonaws\.com/(?P<repository>[\.\/\w-]+):?(?P<tag>.*)$"
)

GCP_ARTIFACT_REGISTRY_URI_REGEX = re.compile(
    r"^(?:https://)?(?P<region>[\w-]+)-docker\.pkg\.dev/(?P<project>[\w-]+)/(?P<repository>[\w-]+)/?(?P<image_name>[\w-]+)?(?P<tag>:.*)?$",
    re.IGNORECASE,
)

S3_URI_RE = re.compile(r"s3://([^/]+)(/(.*))?")
GCS_URI_RE = re.compile(r"gs://([^/]+)(?:/(.*))?")
AZURE_BLOB_REGEX = re.compile(
    r"^https://([^\.]+)\.blob\.core\.windows\.net/([^/]+)/?(.*)$"
)

ARN_PARTITION_RE = re.compile(r"^arn:([^:]+):[^:]*:[^:]*:[^:]*:[^:]*$")

PROJECT_SYNCHRONOUS = "SYNCHRONOUS"

LAUNCH_CONFIG_FILE = "~/.config/wandb/launch-config.yaml"
LAUNCH_DEFAULT_PROJECT = "model-registry"

_logger = logging.getLogger(__name__)
LOG_PREFIX = f"{click.style('launch:', fg='magenta')} "

MAX_ENV_LENGTHS: Dict[str, int] = defaultdict(lambda: 32670)
MAX_ENV_LENGTHS["SageMakerRunner"] = 512

CODE_MOUNT_DIR = "/mnt/wandb"


def load_wandb_config() -> Config:
    """Load wandb config from WANDB_CONFIG environment variable(s).

    The WANDB_CONFIG environment variable is a json string that can contain
    multiple config keys. The WANDB_CONFIG_[0-9]+ environment variables are
    used for environments where there is a limit on the length of environment
    variables. In that case, we shard the contents of WANDB_CONFIG into
    multiple environment variables numbered from 0.

    Returns:
        A dictionary of wandb config values.
    """
    config_str = os.environ.get("WANDB_CONFIG")
    if config_str is None:
        config_str = ""
        idx = 0
        while True:
            chunk = os.environ.get(f"WANDB_CONFIG_{idx}")
            if chunk is None:
                break
            config_str += chunk
            idx += 1
        if idx < 1:
            raise LaunchError(
                "No WANDB_CONFIG or WANDB_CONFIG_[0-9]+ environment variables found"
            )
    wandb_config = Config()
    try:
        env_config = json.loads(config_str)
    except json.JSONDecodeError as e:
        raise LaunchError(f"Failed to parse WANDB_CONFIG: {e}") from e

    wandb_config.update(env_config)
    return wandb_config


def event_loop_thread_exec(func: Any) -> Any:
    """Wrapper for running any function in an awaitable thread on an event loop.

    Example usage:
    ```
    def my_func(arg1, arg2):
        return arg1 + arg2


    future = event_loop_thread_exec(my_func)(2, 2)
    assert await future == 4
    ```

    The returned function must be called within an active event loop.
    """

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        result = cast(
            Any, await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        )
        return result

    return wrapper


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


def get_project_from_job(job: str) -> Optional[str]:
    job_parts = job.split("/")
    if len(job_parts) == 3:
        return job_parts[1]
    return None


def set_project_entity_defaults(
    uri: Optional[str],
    job: Optional[str],
    api: Api,
    project: Optional[str],
    entity: Optional[str],
    launch_config: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], str]:
    # set the target project and entity if not provided
    source_uri = None
    if uri is not None:
        if _is_wandb_uri(uri):
            _, source_uri, _ = parse_wandb_uri(uri)
        elif _is_git_uri(uri):
            source_uri = os.path.splitext(os.path.basename(uri))[0]
    elif job is not None:
        source_uri = get_project_from_job(job)
    if project is None:
        config_project = None
        if launch_config:
            config_project = launch_config.get("project")
        project = config_project or source_uri or ""
    if entity is None:
        entity = get_default_entity(api, launch_config)
    prefix = ""
    if platform.system() != "Windows" and sys.stdout.encoding == "UTF-8":
        prefix = "🚀 "
    wandb.termlog(
        f"{LOG_PREFIX}{prefix}Launching run into {entity}{'/' + project if project else ''}"
    )
    return project, entity


def get_default_entity(api: Api, launch_config: Optional[Dict[str, Any]]):
    config_entity = None
    if launch_config:
        config_entity = launch_config.get("entity")
    return config_entity or api.default_entity


def strip_resource_args_and_template_vars(launch_spec: Dict[str, Any]) -> None:
    if launch_spec.get("resource_args", None) and launch_spec.get(
        "template_variables", None
    ):
        wandb.termwarn(
            "Launch spec contains both resource_args and template_variables, "
            "only one can be set. Using template_variables."
        )
        launch_spec.pop("resource_args")


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
    resource_args: Optional[Dict[str, Any]],
    launch_config: Optional[Dict[str, Any]],
    run_id: Optional[str],
    repository: Optional[str],
    author: Optional[str],
    sweep_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct the launch specification from CLI arguments."""
    # override base config (if supplied) with supplied args
    launch_spec = launch_config if launch_config is not None else {}
    if uri is not None:
        launch_spec["uri"] = uri
    if job is not None:
        launch_spec["job"] = job
    project, entity = set_project_entity_defaults(
        uri,
        job,
        api,
        project,
        entity,
        launch_config,
    )
    launch_spec["entity"] = entity
    if author:
        launch_spec["author"] = author

    launch_spec["project"] = project
    if name:
        launch_spec["name"] = name
    if "docker" not in launch_spec:
        launch_spec["docker"] = {}
    if docker_image:
        launch_spec["docker"]["docker_image"] = docker_image
    if sweep_id:  # all runs in a sweep have this set
        launch_spec["sweep_id"] = sweep_id

    if "resource" not in launch_spec:
        launch_spec["resource"] = resource if resource else None

    if "git" not in launch_spec:
        launch_spec["git"] = {}
    if version:
        launch_spec["git"]["version"] = version

    if "overrides" not in launch_spec:
        launch_spec["overrides"] = {}

    if not isinstance(launch_spec["overrides"].get("args", []), list):
        raise LaunchError("override args must be a list of strings")

    if resource_args:
        launch_spec["resource_args"] = resource_args

    if entry_point:
        launch_spec["overrides"]["entry_point"] = entry_point

    if run_id is not None:
        launch_spec["run_id"] = run_id

    if repository:
        launch_config = launch_config or {}
        if launch_config.get("registry"):
            launch_config["registry"]["url"] = repository
        else:
            launch_config["registry"] = {"url": repository}

    # dont send both resource args and template variables
    strip_resource_args_and_template_vars(launch_spec)

    return launch_spec


def validate_launch_spec_source(launch_spec: Dict[str, Any]) -> None:
    job = launch_spec.get("job")
    docker_image = launch_spec.get("docker", {}).get("docker_image")
    if bool(job) == bool(docker_image):
        raise LaunchError(
            "Exactly one of job or docker_image must be specified in the launch "
            "spec."
        )


def parse_wandb_uri(uri: str) -> Tuple[str, str, str]:
    """Parse wandb uri to retrieve entity, project and run name."""
    ref = WandbReference.parse(uri)
    if not ref or not ref.entity or not ref.project or not ref.run_id:
        raise LaunchError(f"Trouble parsing wandb uri {uri}")
    return (ref.entity, ref.project, ref.run_id)


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
    """Return a list of pip requirements that are not in req_1 but are in req_2."""

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
    """Warn if local python dependencies differ from wandb requirements.txt."""
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


def _fetch_git_repo(dst_dir: str, uri: str, version: Optional[str]) -> Optional[str]:
    """Clones the git repo at ``uri`` into ``dst_dir``.

    checks out commit ``version``. Assumes authentication parameters are
    specified by the environment, e.g. by a Git credential helper.
    """
    # We defer importing git until the last moment, because the import requires that the git
    # executable is available on the PATH, so we only want to fail if we actually need it.

    _logger.info("Fetching git repo")
    ref = GitReference(uri, version)
    if ref is None:
        raise LaunchError(f"Unable to parse git uri: {uri}")
    ref.fetch(dst_dir)
    if version is None:
        version = ref.ref
    return version


def convert_jupyter_notebook_to_script(fname: str, project_dir: str) -> str:
    nbconvert = wandb.util.get_module(
        "nbconvert", "nbformat and nbconvert are required to use launch with notebooks"
    )
    nbformat = wandb.util.get_module(
        "nbformat", "nbformat and nbconvert are required to use launch with notebooks"
    )

    _logger.info("Converting notebook to script")
    new_name = fname.replace(".ipynb", ".py")
    with open(os.path.join(project_dir, fname)) as fh:
        nb = nbformat.reads(fh.read(), nbformat.NO_CONVERT)
        for cell in nb.cells:
            if cell.cell_type == "code":
                source_lines = cell.source.split("\n")
                modified_lines = []
                for line in source_lines:
                    if not line.startswith("!"):
                        modified_lines.append(line)
                cell.source = "\n".join(modified_lines)

    exporter = nbconvert.PythonExporter()
    source, meta = exporter.from_notebook_node(nb)

    with open(os.path.join(project_dir, new_name), "w+") as fh:
        fh.writelines(source)
    return new_name


def to_camel_case(maybe_snake_str: str) -> str:
    if "_" not in maybe_snake_str:
        return maybe_snake_str
    components = maybe_snake_str.split("_")
    return "".join(x.title() if x else "_" for x in components)


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


async def get_kube_context_and_api_client(
    kubernetes: Any,
    resource_args: Dict[str, Any],
) -> Tuple[Any, Any]:
    config_file = resource_args.get("configFile", None)
    context = None
    if config_file is not None or os.path.exists(os.path.expanduser("~/.kube/config")):
        # context only exist in the non-incluster case
        (
            all_contexts,
            active_context,
        ) = kubernetes.config.list_kube_config_contexts(config_file)
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
        # TODO: We should not really be performing this check if the user is not
        # using EKS but I don't see an obvious way to make an eks specific code path
        # right here.
        util.get_module(
            "awscli",
            "awscli is required to load a kubernetes context "
            "from eks. Please run `pip install wandb[launch]` to install it.",
        )
        await kubernetes.config.load_kube_config(config_file, context["name"])
        api_client = await kubernetes.config.new_client_from_config(
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
        resolved_build_config = default_launch_config.get("builder", {})
    elif build_config is not None:
        resolved_build_config = build_config
    resolved_registry_config: Dict[str, Any] = {}
    if registry_config is None and default_launch_config is not None:
        resolved_registry_config = default_launch_config.get("registry", {})
    elif registry_config is not None:
        resolved_registry_config = registry_config
    validate_build_and_registry_configs(resolved_build_config, resolved_registry_config)
    return resolved_build_config, resolved_registry_config


def check_logged_in(api: Api) -> bool:
    """Check if a user is logged in.

    Raises an error if the viewer doesn't load (likely a broken API key). Expected time
    cost is 0.1-0.2 seconds.
    """
    res = api.api.viewer()
    if not res:
        raise LaunchError(
            "Could not connect with current API-key. "
            "Please relogin using `wandb login --relogin`"
            " and try again (see `wandb login --help` for more options)"
        )

    return True


def make_name_dns_safe(name: str) -> str:
    resp = name.replace("_", "-").lower()
    resp = re.sub(r"[^a-z\.\-]", "", resp)
    # Actual length limit is 253, but we want to leave room for the generated suffix
    resp = resp[:200]
    return resp


def warn_failed_packages_from_build_logs(
    log: str, image_uri: str, api: Api, job_tracker: Optional["JobAndRunStatusTracker"]
) -> None:
    match = FAILED_PACKAGES_REGEX.search(log)
    if match:
        _msg = f"Failed to install the following packages: {match.group(1)} for image: {image_uri}. Will attempt to launch image without them."
        wandb.termwarn(_msg)
        if job_tracker is not None:
            res = job_tracker.saver.save_contents(
                _msg, "failed-packages.log", "warning"
            )
            api.update_run_queue_item_warning(
                job_tracker.run_queue_item_id,
                "Some packages were not successfully installed during the build",
                "build",
                res,
            )


def docker_image_exists(docker_image: str, should_raise: bool = False) -> bool:
    """Check if a specific image is already available.

    Optionally raises an exception if the image is not found.
    """
    _logger.info("Checking if base image exists...")
    try:
        docker.run(["docker", "image", "inspect", docker_image])
        return True
    except (docker.DockerError, ValueError) as e:
        if should_raise:
            raise e
        _logger.info("Base image not found. Generating new base image")
        return False


def pull_docker_image(docker_image: str) -> None:
    """Pull the requested docker image."""
    try:
        docker.run(["docker", "pull", docker_image])
    except docker.DockerError as e:
        raise LaunchError(f"Docker server returned error: {e}")


def macro_sub(original: str, sub_dict: Dict[str, Optional[str]]) -> str:
    """Substitute macros in a string.

    Macros occur in the string in the ${macro} format. The macro names are
    substituted with their values from the given dictionary. If a macro
    is not found in the dictionary, it is left unchanged.

    Args:
        original: The string to substitute macros in.
        sub_dict: A dictionary mapping macro names to their values.

    Returns:
        The string with the macros substituted.
    """
    return MACRO_REGEX.sub(
        lambda match: str(sub_dict.get(match.group(1), match.group(0))), original
    )


def recursive_macro_sub(source: Any, sub_dict: Dict[str, Optional[str]]) -> Any:
    """Recursively substitute macros in a parsed JSON or YAML blob.

    Macros occur in strings at leaves of the blob in the ${macro} format.
    The macro names are substituted with their values from the given dictionary.
    If a macro is not found in the dictionary, it is left unchanged.

    Arguments:
        source: The JSON or YAML blob to substitute macros in.
        sub_dict: A dictionary mapping macro names to their values.

    Returns:
        The blob with the macros substituted.
    """
    if isinstance(source, str):
        return macro_sub(source, sub_dict)
    elif isinstance(source, list):
        return [recursive_macro_sub(item, sub_dict) for item in source]
    elif isinstance(source, dict):
        return {
            key: recursive_macro_sub(value, sub_dict) for key, value in source.items()
        }
    else:
        return source


def fetch_and_validate_template_variables(
    runqueue: Any, fields: dict
) -> Dict[str, Any]:
    template_variables = {}

    variable_schemas = {}
    for tv in runqueue.template_variables:
        variable_schemas[tv["name"]] = json.loads(tv["schema"])

    for field in fields:
        field_parts = field.split("=")
        if len(field_parts) != 2:
            raise LaunchError(
                f'--set-var value must be in the format "--set-var key1=value1", instead got: {field}'
            )
        key, val = field_parts
        if key not in variable_schemas:
            raise LaunchError(
                f"Queue {runqueue.name} does not support overriding {key}."
            )
        schema = variable_schemas.get(key, {})
        field_type = schema.get("type")
        try:
            if field_type == "integer":
                val = int(val)
            elif field_type == "number":
                val = float(val)

        except ValueError:
            raise LaunchError(f"Value for {key} must be of type {field_type}.")
        template_variables[key] = val
    return template_variables


def get_entrypoint_file(entrypoint: List[str]) -> Optional[str]:
    """Get the entrypoint file from the given command.

    Args:
        entrypoint (List[str]): List of command and arguments.

    Returns:
        Optional[str]: The entrypoint file if found, otherwise None.
    """
    if not entrypoint:
        return None
    if entrypoint[0].endswith(".py") or entrypoint[0].endswith(".sh"):
        return entrypoint[0]
    if len(entrypoint) < 2:
        return None
    return entrypoint[1]


def get_current_python_version() -> Tuple[str, str]:
    full_version = sys.version.split()[0].split(".")
    major = full_version[0]
    version = ".".join(full_version[:2]) if len(full_version) >= 2 else major + ".0"
    return version, major
