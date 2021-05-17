import json
import os
import socket

from . import files as sm_files


def parse_sm_secrets():
    """We read our api_key from secrets.env in SageMaker"""
    env_dict = dict()
    # Set secret variables
    if os.path.exists(sm_files.SM_SECRETS):
        for line in open(sm_files.SM_SECRETS, "r"):
            key, val = line.strip().split("=", 1)
            env_dict[key] = val
    return env_dict


def parse_sm_resources():
    run_dict = dict()
    env_dict = dict()
    run_id = os.getenv("TRAINING_JOB_NAME")
    if run_id:
        run_dict["run_id"] = "-".join(
            [run_id, os.getenv("CURRENT_HOST", socket.gethostname())]
        )
    conf = json.load(open(sm_files.SM_RESOURCE_CONFIG))
    if len(conf["hosts"]) > 1:
        run_dict["run_group"] = os.getenv("TRAINING_JOB_NAME")
    env_dict = parse_sm_secrets()
    return run_dict, env_dict
