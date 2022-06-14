import os
import subprocess
import wandb
import pytest

cmd = ["python", "./script/job_generator.py"]

subprocess.check_call(cmd)

api = wandb.Api()
job = api.job("test-job/job_source-test-.scriptjob_generator.py:v0")
assert job._job_artifact is not None
assert job.name == "test-job/job_source-test-.scriptjob_generator.py:v0"
# manually insert defaults since mock server doesn't support metadata
job._job_artifact.metadata["config_defaults"] = {"epochs": 5, "lr": 0.1, "foo": "bar"}
with pytest.raises(TypeError):
    job.call(config={"batch_size": 64})
