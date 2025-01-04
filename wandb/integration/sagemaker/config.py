from __future__ import annotations

import json
import os
import re
import warnings
from typing import Any

from . import files as sm_files


def is_using_sagemaker() -> bool:
    """Returns whether we're in a SageMaker environment."""
    return (
        os.path.exists(sm_files.SM_PARAM_CONFIG)  #
        or "SM_TRAINING_ENV" in os.environ
    )


def parse_sm_config() -> dict[str, Any]:
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

    if os.path.exists(sm_files.SM_PARAM_CONFIG):
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

    if env := os.environ.get("SM_TRAINING_ENV"):
        try:
            conf.update(json.loads(env))
        except json.JSONDecodeError:
            warnings.warn(
                "Failed to parse SM_TRAINING_ENV not valid JSON string",
                stacklevel=2,
            )

    return conf
