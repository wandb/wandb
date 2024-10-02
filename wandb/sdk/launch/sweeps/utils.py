import json
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import yaml

import wandb
from wandb import util
from wandb.sdk.launch.errors import LaunchError

if TYPE_CHECKING:
    from wandb.apis.public import Api as PublicApi

DEFAULT_SWEEP_COMMAND: List[str] = [
    "${env}",
    "${interpreter}",
    "${program}",
    "${args}",
]
SWEEP_COMMAND_ENV_VAR_REGEX = re.compile(r"\$\{envvar\:([A-Z0-9_]*)\}")


def parse_sweep_id(parts_dict: dict) -> Optional[str]:
    """In place parse sweep path from parts dict.

    Arguments:
        parts_dict (dict): dict(entity=,project=,name=).  Modifies dict inplace.

    Returns:
        None or str if there is an error
    """
    entity = None
    project = None
    sweep_id = parts_dict.get("name")
    if not isinstance(sweep_id, str):
        return "Expected string sweep_id"

    sweep_split = sweep_id.split("/")
    if len(sweep_split) == 1:
        pass
    elif len(sweep_split) == 2:
        split_project, sweep_id = sweep_split
        project = split_project or project
    elif len(sweep_split) == 3:
        split_entity, split_project, sweep_id = sweep_split
        project = split_project or project
        entity = split_entity or entity
    else:
        return (
            "Expected sweep_id in form of sweep, project/sweep, or entity/project/sweep"
        )
    parts_dict.update(dict(name=sweep_id, project=project, entity=entity))
    return None


def sweep_config_err_text_from_jsonschema_violations(violations: List[str]) -> str:
    """Consolidate schema violation strings from wandb/sweeps into a single string.

    Parameters
    ----------
    violations: list of str
        The warnings to render.

    Returns:
    -------
    violation: str
        The consolidated violation text.

    """
    violation_base = (
        "Malformed sweep config detected! This may cause your sweep to behave in unexpected ways.\n"
        "To avoid this, please fix the sweep config schema violations below:"
    )

    for i, warning in enumerate(violations):
        violations[i] = f"  Violation {i + 1}. {warning}"
    violation = "\n".join([violation_base] + violations)

    return violation


def handle_sweep_config_violations(warnings: List[str]) -> None:
    """Echo sweep config schema violation warnings from Gorilla to the terminal.

    Parameters
    ----------
    warnings: list of str
        The warnings to render.
    """
    warning = sweep_config_err_text_from_jsonschema_violations(warnings)
    if len(warnings) > 0:
        wandb.termwarn(warning)


def load_sweep_config(sweep_config_path: str) -> Optional[Dict[str, Any]]:
    """Load a sweep yaml from path."""
    try:
        yaml_file = open(sweep_config_path)
    except OSError:
        wandb.termerror(f"Couldn't open sweep file: {sweep_config_path}")
        return None
    try:
        config: Optional[Dict[str, Any]] = yaml.safe_load(yaml_file)
    except yaml.YAMLError as err:
        wandb.termerror(f"Error in configuration file: {err}")
        return None
    if not config:
        wandb.termerror("Configuration file is empty")
        return None
    return config


def load_launch_sweep_config(config: Optional[str]) -> Any:
    if not config:
        return {}

    parsed_config = util.load_json_yaml_dict(config)
    if parsed_config is None:
        raise LaunchError(f"Could not load config from {config}. Check formatting")
    return parsed_config


def construct_scheduler_args(
    sweep_config: Dict[str, Any],
    queue: str,
    project: str,
    author: Optional[str] = None,
    return_job: bool = False,
) -> Union[List[str], Dict[str, str], None]:
    """Construct sweep scheduler args.

    logs error and returns None if misconfigured,
    otherwise returns args as a dict if is_job else a list of strings.
    """
    job = sweep_config.get("job")
    image_uri = sweep_config.get("image_uri")
    if not job and not image_uri:  # don't allow empty string
        wandb.termerror(
            "No 'job' nor 'image_uri' top-level key found in sweep config, exactly one is required for a launch-sweep"
        )
        return None
    elif job and image_uri:
        wandb.termerror(
            "Sweep config has both 'job' and 'image_uri' but a launch-sweep can use only one"
        )
        return None

    # if scheduler is a job, return args as dict
    if return_job:
        args_dict: Dict[str, str] = {
            "sweep_id": "WANDB_SWEEP_ID",
            "queue": queue,
            "project": project,
        }
        if job:
            args_dict["job"] = job
        elif image_uri:
            args_dict["image_uri"] = image_uri

        if author:
            args_dict["author"] = author

        return args_dict

    # scheduler uses cli commands, pass args as param list
    args = [
        "--queue",
        f"{queue!r}",
        "--project",
        f"{project!r}",
    ]
    if author:
        args += [
            "--author",
            f"{author!r}",
        ]
    if job:
        args += [
            "--job",
            f"{job!r}",
        ]
    elif image_uri:
        args += ["--image_uri", image_uri]

    return args


def create_sweep_command(command: Optional[List] = None) -> List:
    """Return sweep command, filling in environment variable macros."""
    # Start from default sweep command
    command = command or DEFAULT_SWEEP_COMMAND
    for i, chunk in enumerate(command):
        # Replace environment variable macros
        # Search a str(chunk), but allow matches to be of any (ex: int) type
        if SWEEP_COMMAND_ENV_VAR_REGEX.search(str(chunk)):
            # Replace from backwards forwards
            matches = list(SWEEP_COMMAND_ENV_VAR_REGEX.finditer(chunk))
            for m in matches[::-1]:
                # Default to just leaving as is if environment variable does not exist
                _var: str = os.environ.get(m.group(1), m.group(1))
                command[i] = f"{command[i][:m.start()]}{_var}{command[i][m.end():]}"
    return command


def create_sweep_command_args(command: Dict) -> Dict[str, Any]:
    """Create various formats of command arguments for the agent.

    Raises:
        ValueError: improperly formatted command dict

    """
    if "args" not in command:
        raise ValueError('No "args" found in command: {}'.format(command))
    # four different formats of command args
    # (1) standard command line flags (e.g. --foo=bar)
    flags: List[str] = []
    # (2) flags without hyphens (e.g. foo=bar)
    flags_no_hyphens: List[str] = []
    # (3) flags with false booleans omitted  (e.g. --foo)
    flags_no_booleans: List[str] = []
    # (4) flags as a dictionary (used for constructing a json)
    flags_dict: Dict[str, Any] = {}
    # (5) flags without equals (e.g. --foo bar)
    args_no_equals: List[str] = []
    for param, config in command["args"].items():
        # allow 'None' as a valid value, but error if no value is found
        try:
            _value: Any = config["value"]
        except KeyError:
            raise ValueError('No "value" found for command["args"]["{}"]'.format(param))

        _flag: str = f"{param}={_value}"
        flags.append("--" + _flag)
        flags_no_hyphens.append(_flag)
        args_no_equals += [f"--{param}", str(_value)]
        if isinstance(_value, bool):
            # omit flags if they are boolean and false
            if _value:
                flags_no_booleans.append("--" + param)
        else:
            flags_no_booleans.append("--" + _flag)
        flags_dict[param] = _value
    return {
        "args": flags,
        "args_no_equals": args_no_equals,
        "args_no_hyphens": flags_no_hyphens,
        "args_no_boolean_flags": flags_no_booleans,
        "args_json": [json.dumps(flags_dict)],
        "args_dict": flags_dict,
    }


def make_launch_sweep_entrypoint(
    args: Dict[str, Any], command: Optional[List[str]]
) -> Tuple[Optional[List[str]], Any]:
    """Use args dict from create_sweep_command_args to construct entrypoint.

    If replace is True, remove macros from entrypoint, fill them in with args
    and then return the args in separate return value.
    """
    if not command:
        return None, None

    entry_point = create_sweep_command(command)
    macro_args = {}
    for macro in args:
        mstr = "${" + macro + "}"
        if mstr in entry_point:
            idx = entry_point.index(mstr)
            # only supports 1 macro per entrypoint
            macro_args = args[macro]
            entry_point = entry_point[:idx] + entry_point[idx + 1 :]

    if len(entry_point) == 0:
        return None, macro_args

    return entry_point, macro_args


def check_job_exists(public_api: "PublicApi", job: Optional[str]) -> bool:
    """Check if the job exists using the public api.

    Returns: True if no job is passed, or if the job exists.
    Returns: False if the job is misformatted or doesn't exist.
    """
    if not job:
        return True

    try:
        public_api.job(job)
    except Exception as e:
        wandb.termerror(f"Failed to load job. {e}")
        return False
    return True


def get_previous_args(
    run_spec: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse through previous scheduler run_spec.

    returns scheduler_args and settings.
    """
    scheduler_args = (
        run_spec.get("overrides", {}).get("run_config", {}).get("scheduler", {})
    )
    # also pipe through top level resource setup
    if run_spec.get("resource"):
        scheduler_args["resource"] = run_spec["resource"]
    if run_spec.get("resource_args"):
        scheduler_args["resource_args"] = run_spec["resource_args"]

    settings = run_spec.get("overrides", {}).get("run_config", {}).get("settings", {})

    return scheduler_args, settings
