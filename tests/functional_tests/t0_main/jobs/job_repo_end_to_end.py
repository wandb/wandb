import os
import subprocess

import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.util import to_forward_slash_path


# this test is kind of hacky, it piggy backs off of the existing wandb/client git repo to construct the job
# should probably have it use wandb_examples or something
cmd = ["python", "job_repo_creation.py"]

subprocess.check_call(cmd)

api = wandb.Api()
job = api.job("job-gitgithub.comwandbclient.git_job_repo_creation.py:v0")

assert job._job_artifact is not None
assert job.name == "job-gitgithub.comwandbclient.git_job_repo_creation.py:v0"
assert job._source_info["source_type"] == "repo"
assert job._input_types == TypeRegistry.type_of({"foo": "bar", "lr": 0.1, "epochs": 5})

# manually insert defaults since mock server doesn't support metadata
job._job_artifact.metadata["config_defaults"] = {"epochs": 5, "lr": 0.1, "foo": "bar"}
with pytest.raises(TypeError):
    job.call(config={"batch_size": 64})


internal_api = InternalApi()
kwargs = {
    "uri": None,
    "job": "job-gitgithub.comwandbclient.git_job_repo_creation.py:v0",
    "api": internal_api,
    "launch_spec": {},
    "target_entity": api.default_entity,
    "target_project": "test-job",
    "name": None,
    "docker_config": {},
    "git_info": {},
    "overrides": {},
    "resource": "local",
    "resource_args": {},
    "cuda": False,
}
lp = LaunchProject(**kwargs)

job.configure_launch_project(lp)
assert (
    to_forward_slash_path(lp.get_single_entry_point().compute_command({})[1])
    == "functional_tests/jobs/job_repo_creation.py"
)
assert "requirements.frozen.txt" in os.listdir(lp.project_dir)
