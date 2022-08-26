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
cmd = ["python", "job_repo_creation.py", "--log-test"]

subprocess.check_call(cmd)

api = wandb.Api()
job = api.job(
    "job-git_github.com_wandb_wandb.git_tests_functional_tests_t0_main_jobs_job_repo_creation.py:v0"
)

assert job._job_artifact is not None
assert (
    job.name
    == "job-git_github.com_wandb_wandb.git_tests_functional_tests_t0_main_jobs_job_repo_creation.py:v0"
)
assert job._source_info["source_type"] == "repo"
assert job._input_types == TypeRegistry.type_of({"foo": "bar", "lr": 0.1, "epochs": 5})

with pytest.raises(TypeError):
    job.call(config={"batch_size": 64})


internal_api = InternalApi()
kwargs = {
    "uri": None,
    "job": "job-git_github.com_wandb_wandb.git_tests_functional_tests_t0_main_jobs_job_repo_creation.py:v0",
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
    "run_id": None,
}
lp = LaunchProject(**kwargs)

job.configure_launch_project(lp)
command = lp.get_single_entry_point().compute_command({})
print(to_forward_slash_path(command[1]))
assert (
    to_forward_slash_path(command[1])
    == "tests/functional_tests/t0_main/jobs/job_repo_creation.py"
)
assert "requirements.frozen.txt" in os.listdir(lp.project_dir)
print(command)
assert lp.override_args == ["--log-test"]
