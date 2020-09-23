import json
import os
import re

import six

from . import files as sm_files


def parse_sm_config():
    """Attempts to parse SageMaker configuration returning False if it can't find it"""
    if os.path.exists(sm_files.SM_PARAM_CONFIG) and os.path.exists(
        sm_files.SM_RESOURCE_CONFIG
    ):
        conf = {}
        conf["sagemaker_training_job_name"] = os.getenv("TRAINING_JOB_NAME")
        # Hyper-parameter searchs quote configs...
        for k, v in six.iteritems(json.load(open(sm_files.SM_PARAM_CONFIG))):
            cast = v.strip('"')
            if re.match(r"^[-\d]+$", cast):
                cast = int(cast)
            elif re.match(r"^[-.\d]+$", cast):
                cast = float(cast)
            conf[k] = cast
        return conf
    else:
        return False
