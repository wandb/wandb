import json
import os
import socket

from . import files as sm_files


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
        run_dict["group"] = os.getenv("TRAINING_JOB_NAME")
    # Set secret variables
    if os.path.exists(sm_files.SM_SECRETS):
        for line in open(sm_files.SM_SECRETS, "r"):
            key, val = line.strip().split("=", 1)
            env_dict[key] = val
    return run_dict, env_dict
