import os
import secrets
import socket
import string
from typing import Dict, Tuple

from . import files as sm_files


def parse_sm_secrets() -> Dict[str, str]:
    """We read our api_key from secrets.env in SageMaker."""
    env_dict = dict()
    # Set secret variables
    if os.path.exists(sm_files.SM_SECRETS):
        for line in open(sm_files.SM_SECRETS):
            key, val = line.strip().split("=", 1)
            env_dict[key] = val
    return env_dict


def parse_sm_resources() -> Tuple[Dict[str, str], Dict[str, str]]:
    run_dict = dict()
    run_id = os.getenv("TRAINING_JOB_NAME")

    if run_id and os.getenv("WANDB_RUN_ID") is None:
        suffix = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
        )
        run_dict["run_id"] = "-".join(
            [run_id, suffix, os.getenv("CURRENT_HOST", socket.gethostname())]
        )
    run_dict["run_group"] = os.getenv("TRAINING_JOB_NAME")
    env_dict = parse_sm_secrets()
    return run_dict, env_dict
