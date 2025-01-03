from __future__ import annotations

import os
import secrets
import socket
import string

from . import files as sm_files


def parse_sm_secrets() -> dict[str, str]:
    """We read our api_key from secrets.env in SageMaker."""
    env_dict = dict()
    # Set secret variables
    if os.path.exists(sm_files.SM_SECRETS):
        for line in open(sm_files.SM_SECRETS):
            key, val = line.strip().split("=", 1)
            env_dict[key] = val
    return env_dict


def run_id_and_group() -> tuple[str, str] | None:
    """Returns a new ID and group for a run using SageMaker."""
    # Added in https://github.com/wandb/wandb/pull/3290.
    #
    # Prevents SageMaker from overriding the run ID configured
    # in environment variables. Note, however, that it will still
    # override a run ID passed explicitly to `wandb.init()`.
    if os.getenv("WANDB_RUN_ID"):
        return None

    run_group = os.getenv("TRAINING_JOB_NAME")
    if not run_group:
        return None

    alphanumeric = string.ascii_lowercase + string.digits
    random = "".join(secrets.choice(alphanumeric) for _ in range(6))

    host = os.getenv("CURRENT_HOST", socket.gethostbyname())

    return f"{run_group}-{random}-{host}", run_group
