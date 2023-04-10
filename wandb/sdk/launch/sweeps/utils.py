from typing import Any, Dict, List, Optional, Union

import yaml

import wandb
from wandb import util
from wandb.sdk.launch.utils import LaunchError


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


def construct_scheduler_entrypoint(
    sweep_config: Dict[str, Any],
    queue: str,
    project: str,
    num_workers: Union[str, int],
) -> Optional[List[str]]:
    """Construct a sweep scheduler run spec.

    logs error and returns None if misconfigured, otherwise returns entrypoint
    """
    job = sweep_config.get("job")
    image_uri = sweep_config.get("image_uri")
    if not job and not image_uri:  # don't allow empty string
        wandb.termerror(
            "No 'job' nor 'image_uri' top-level key found in sweep config, exactly one is required for a launch-sweep"
        )
        return []
    elif job and image_uri:
        wandb.termerror(
            "Sweep config has both 'job' and 'image_uri' but a launch-sweep can use only one"
        )
        return []

    if type(num_workers) is str:
        if num_workers.isdigit():
            num_workers = int(num_workers)
        else:
            wandb.termerror(
                "'num_workers' must be an integer or a string that can be parsed as an integer"
            )
            return []

    entrypoint = [
        "wandb",
        "scheduler",
        "WANDB_SWEEP_ID",
        "--queue",
        f"{queue!r}",
        "--project",
        project,
        "--num_workers",
        f"{num_workers}",
    ]

    if job:
        if ":" not in job:
            wandb.termwarn("No alias specified for job, defaulting to 'latest'")
            job += ":latest"

        entrypoint += ["--job", job]
    elif image_uri:
        entrypoint += ["--image_uri", image_uri]

    return entrypoint
