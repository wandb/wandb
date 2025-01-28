from __future__ import annotations

import os
import secrets
import socket
import string

import wandb

from . import config
from . import files as sm_files


def set_run_id(run_settings: wandb.Settings) -> bool:
    """Set a run ID and group when using SageMaker.

    Returns whether the ID and group were updated.
    """
    # Added in https://github.com/wandb/wandb/pull/3290.
    #
    # Prevents SageMaker from overriding the run ID configured
    # in environment variables. Note, however, that it will still
    # override a run ID passed explicitly to `wandb.init()`.
    if os.getenv("WANDB_RUN_ID"):
        return False

    run_group = os.getenv("TRAINING_JOB_NAME")
    if not run_group:
        return False

    alphanumeric = string.ascii_lowercase + string.digits
    random = "".join(secrets.choice(alphanumeric) for _ in range(6))

    host = os.getenv("CURRENT_HOST", socket.gethostname())

    run_settings.run_id = f"{run_group}-{random}-{host}"
    run_settings.run_group = run_group
    return True


def set_global_settings(settings: wandb.Settings) -> None:
    """Set global W&B settings based on the SageMaker environment."""
    if env := parse_sm_secrets():
        settings.update_from_env_vars(env)

    # The SageMaker config may contain an API key, in which case it
    # takes precedence over the value in the secrets. It's unclear
    # whether this is by design, or by accident; we keep it for
    # backward compatibility for now.
    sm_config = config.parse_sm_config()
    if api_key := sm_config.get("wandb_api_key"):
        settings.api_key = api_key


def parse_sm_secrets() -> dict[str, str]:
    """We read our api_key from secrets.env in SageMaker."""
    env_dict = dict()
    # Set secret variables
    if os.path.exists(sm_files.SM_SECRETS):
        for line in open(sm_files.SM_SECRETS):
            key, val = line.strip().split("=", 1)
            env_dict[key] = val
    return env_dict
