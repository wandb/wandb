import json
import os
import re
from typing import Any, Dict
import warnings

from . import files as sm_files


def is_running_in_sagemaker(self):
    return


def parse_sm_config() -> Dict[str, Any]:
    """Attempt to parse SageMaker configuration.

    Returns:
        A dictionary of SageMaker config keys/values or empty dict if not found.
        SM_TRAINING_ENV is a json string of the training environment variables set by SageMaker.
        and is only available when running in SageMaker, but not in local mode.
        SM_TRAINING_ENV is set by the SageMaker container and contains arguments such as
        hyperparameters and arguments passed to the training job.
    """
    conf = {}
    if os.path.exists(sm_files.SM_PARAM_CONFIG) and os.path.exists(
        sm_files.SM_RESOURCE_CONFIG
    ):
        conf["sagemaker_training_job_name"] = os.getenv("TRAINING_JOB_NAME")
        # Hyperparameter searches quote configs...
        for k, v in json.load(open(sm_files.SM_PARAM_CONFIG)).items():
            cast = v.strip('"')
            if re.match(r"^-?[\d]+$", cast):
                cast = int(cast)
            elif re.match(r"^-?[.\d]+$", cast):
                cast = float(cast)
            conf[k] = cast
    if "SM_TRAINING_ENV" in os.environ:
        try:
            conf = {**conf, **json.loads(os.environ["SM_TRAINING_ENV"])}
        except:
            warnings.warn(
                """
                Failed to parse SM_TRAINING_ENV -- 
                either not valid JSON string, running in local mode,
                and will not be included in your wandb config
                """
            )
    return conf
