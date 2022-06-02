import json
import os
import re

from . import files as sm_files


def parse_sm_config():
    """Attempts to parse SageMaker configuration.

    Returns:
        A dictionary of SageMaker config keys/values or empty dict if not found.
    """
    conf = {}
    if os.path.exists(sm_files.SM_PARAM_CONFIG) and os.path.exists(
        sm_files.SM_RESOURCE_CONFIG
    ):
        conf["sagemaker_training_job_name"] = os.getenv("TRAINING_JOB_NAME")
        # Hyperparameter searches quote configs...
        for k, v in json.load(open(sm_files.SM_PARAM_CONFIG)).items():
            cast = v.strip('"')
            if re.match(r"^[-\d]+$", cast):
                cast = int(cast)
            elif re.match(r"^[-.\d]+$", cast):
                cast = float(cast)
            conf[k] = cast
    return conf
