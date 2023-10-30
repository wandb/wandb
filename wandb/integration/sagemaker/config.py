import json
import os
import re
import warnings
from typing import Any, Dict

from . import files as sm_files


def parse_sm_config() -> Dict[str, Any]:
    """Parses SageMaker configuration.

    Returns:
        A dictionary of SageMaker config keys/values
        or an empty dict if not found.
        SM_TRAINING_ENV is a json string of the
        training environment variables set by SageMaker
        and is only available when running in SageMaker,
        but not in local mode.
        SM_TRAINING_ENV is set by the SageMaker container and
        contains arguments such as hyperparameters
        and arguments passed to the training job.
    """
    conf = {}

    if os.path.exists(sm_files.SM_PARAM_CONFIG) and os.path.exists(
        sm_files.SM_RESOURCE_CONFIG
    ):
        conf["sagemaker_training_job_name"] = os.getenv("TRAINING_JOB_NAME")

        # Hyperparameter searches quote configs...
        with open(sm_files.SM_PARAM_CONFIG) as fid:
            for key, val in json.load(fid).items():
                cast = val.strip('"')
                if re.match(r"^-?[\d]+$", cast):
                    cast = int(cast)
                elif re.match(r"^-?[.\d]+$", cast):
                    cast = float(cast)
                conf[key] = cast

    if "SM_TRAINING_ENV" in os.environ:
        try:
            conf = {**conf, **json.loads(os.environ["SM_TRAINING_ENV"])}
        except json.JSONDecodeError:
            warnings.warn(
                "Failed to parse SM_TRAINING_ENV not valid JSON string", stacklevel=2
            )

    return conf
