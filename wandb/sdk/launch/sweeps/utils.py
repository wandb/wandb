from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb import util
from wandb.sdk.launch.utils import LaunchError


def _load_launch_sweep_cli_params(
    launch_config: Optional[Dict[str, Any]], queue: Optional[str]
) -> Tuple[Dict[str, Any], str]:
    if launch_config:
        launch_config = util.load_json_yaml_dict(launch_config)
        if launch_config is None:
            raise LaunchError(f"Invalid format for launch config at {launch_config}")
        wandb.termlog(f"Using launch 🚀 with config: {launch_config}")
    else:
        launch_config = {}

    queue = queue or launch_config.get("queue")
    if launch_config and not queue:
        raise LaunchError(
            "No queue passed from CLI or in launch config for launch-sweep"
        )

    return launch_config, queue


def construct_scheduler_entrypoint(
    sweep_config: Dict[str, Any],
    queue: str,
    project: str,
    num_workers: int,
) -> Optional[List[str]]:
    """Construct a sweep scheduler run spec.

    logs error and returns None if misconfigured, otherwise returns entrypoint
    """
    job = sweep_config.get("job")
    image_uri = sweep_config.get("image_uri")
    if not job and not image_uri:  # don't allow empty string
        wandb.termerror("No 'job' nor 'image_uri' found in sweep config")
        return
    elif job and image_uri:
        wandb.termerror("Sweep has both 'job' and 'image_uri'")
        return

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
