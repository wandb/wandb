from typing import Any, Dict, List

import wandb
from wandb.sdk.launch.utils import LaunchError


def construct_scheduler_entrypoint(
    scheduler_config: Dict[str, Any],
    sweep_config: Dict[str, Any],
    queue: str,
    project: str,
) -> List[str]:
    """Construct a sweep scheduler run spec.

    raises exception if misconfigured, otherwise returns entrypoint
    """
    job = sweep_config.get("job")
    image_uri = sweep_config.get("image_uri")
    if not job and not image_uri:  # don't allow empty string
        raise LaunchError("No 'job' nor 'image_uri' found in sweep config")
    elif job and image_uri:
        raise LaunchError("Sweep has both 'job' and 'image_uri'")

    num_workers = f'{scheduler_config.get("num_workers")}'
    if num_workers is None or not str.isdigit(num_workers):
        num_workers = "8"  # default

    entrypoint = [
        "wandb",
        "scheduler",
        "WANDB_SWEEP_ID",
        "--queue",
        f"{queue!r}",
        "--project",
        project,
        "--num_workers",
        num_workers,
    ]

    if job:
        if ":" not in job:
            wandb.termwarn("No alias specified for job, defaulting to 'latest'")
            job += ":latest"

        entrypoint += ["--job", job]
    elif image_uri:
        entrypoint += ["--image_uri", image_uri]

    return entrypoint
