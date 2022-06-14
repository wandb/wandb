import subprocess
import wandb
import pytest
from wandb.sdk.data_types._dtypes import TypeRegistry

cmd = ["python", "./script/container_job_generator.py"]

subprocess.check_call(cmd)

api = wandb.Api()
job = api.job("job_my-test-container:v0")

assert job._job_artifact is not None
assert job.name == "job_my-test-container:v0"
assert job._source_info["source_type"] == "container"
assert job._input_types == TypeRegistry.type_of({"foo": "bar", "lr": 0.1, "epochs": 5})

# manually insert defaults since mock server doesn't support metadata
job._job_artifact.metadata["config_defaults"] = {"epochs": 5, "lr": 0.1, "foo": "bar"}
with pytest.raises(TypeError):
    job.call(config={"batch_size": 64})
