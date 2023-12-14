from unittest import mock

import wandb
from wandb.apis import internal


def test_repo_job_creation(live_mock_server, test_settings, git_repo_fn):
    _ = git_repo_fn(commit_msg="initial commit")
    test_settings.update({"program_relpath": "./blah/test_program.py"})
    with wandb.init(settings=test_settings) as run:
        run.log({"test": 1})
    ctx = live_mock_server.get_ctx()
    artifact_name = list(ctx["artifacts"].keys())[0]
    assert artifact_name == wandb.util.make_artifact_name_safe(
        f"job-{run._settings.git_remote_url}_{run._settings.program_relpath}"
    )


def test_artifact_job_creation(live_mock_server, test_settings, runner):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write('print("test")')
        test_settings.update(
            {
                "disable_git": True,
                "program_relpath": "./blah/test_program.py",
            }
        )
        run = wandb.init(settings=test_settings)
        run.log_code()
        run.finish()
        ctx = live_mock_server.get_ctx()
        code_artifact_name = list(ctx["artifacts"].keys())[0]
        job_artifact_name = list(ctx["artifacts"].keys())[1]
        assert job_artifact_name == f"job-{code_artifact_name}"


def test_container_job_creation(live_mock_server, test_settings):
    test_settings.update({"disable_git": True})
    with mock.patch.dict("os.environ", WANDB_DOCKER="dummy-container:docker-tag"):
        run = wandb.init(settings=test_settings)
        run.finish()
        ctx = live_mock_server.get_ctx()
        artifact_name = list(ctx["artifacts"].keys())[0]
        assert artifact_name == "job-dummy-container"
        aliases = [
            x["alias"] for x in ctx["artifacts"]["job-dummy-container"][0]["aliases"]
        ]
        assert "docker-tag" in aliases
        assert "latest" in aliases


"""Test internal APIs"""


def test_get_run_state(test_settings):
    _api = internal.Api()
    res = _api.get_run_state("test", "test", "test")
    assert res == "running", "Test run must have state running"
