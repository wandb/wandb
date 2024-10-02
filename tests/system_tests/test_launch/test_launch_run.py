import json
from unittest import mock

import wandb
from wandb.apis import internal, public
from wandb.sdk.internal import job_builder
from wandb.sdk.launch._project_spec import _inject_wandb_config_env_vars
from wandb.util import make_artifact_name_safe


def test_run_use_job_env_var(runner, relay_server, test_settings, user, wandb_init):
    art_name = "job-my-test-image"
    artifact_name = f"{user}/uncategorized/{art_name}"
    artifact_env = json.dumps({"_wandb_job": f"{artifact_name}:latest"})
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", WANDB_ARTIFACTS=artifact_env
    ):
        artifact = job_builder.JobArtifact(name=art_name)
        filename = "file1.txt"
        with open(filename, "w") as fp:
            fp.write("hello!")
        artifact.add_file(filename)
        with wandb_init(user) as run:
            run.log_artifact(artifact)
            artifact.wait()
        with relay_server() as relay:
            with wandb_init(user, settings=test_settings({"launch": True})) as run:
                run.log({"x": 2})
            use_count = 0
            for data in relay.context.raw_data:
                assert "mutation CreateArtifact(" not in data.get("request", {}).get(
                    "query", ""
                )
                if "mutation UseArtifact(" in data.get("request", {}).get("query", ""):
                    use_count += 1
        assert use_count == 1


def test_run_in_launch_context_with_multi_config_env_var(
    runner, test_settings, monkeypatch, wandb_init
):
    with runner.isolated_filesystem():
        config_env_vars = {}
        _inject_wandb_config_env_vars({"epochs": 10}, config_env_vars, 5)
        for k in config_env_vars.keys():
            monkeypatch.setenv(k, config_env_vars[k])
        settings = test_settings()
        settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb_init(settings=settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        assert run.config.epochs == 10
        assert run.config.lr == 0.004


def test_run_in_launch_context_with_malformed_env_vars(
    runner, test_settings, monkeypatch, capsys, wandb_init, user
):
    with runner.isolated_filesystem():
        monkeypatch.setenv("WANDB_ARTIFACTS", '{"epochs: 6}')
        monkeypatch.setenv("WANDB_CONFIG", '{"old_name": {"name": "test:v0"')
        settings = test_settings()
        settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb_init(settings=settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        _, err = capsys.readouterr()
        assert "Malformed WANDB_CONFIG, using original config" in err
        assert "Malformed WANDB_ARTIFACTS, using original artifacts" in err


def test_repo_job_creation(test_settings, user, wandb_init):
    settings = test_settings()
    settings.update(
        {
            "program_relpath": "./blah/test_program.py",
            "git_remote_url": "https://github.com/test/repo",
            "git_commit": "asdasdasdasd",
        }
    )
    with wandb_init(settings=settings) as run:
        run.log({"test": 1})
    api = public.Api()
    job_name = make_artifact_name_safe(
        f"job-{run._settings.git_remote_url}_{run._settings.program_relpath}"
    )
    artifact = api.artifact(f"{user}/{run._settings.project}/{job_name}:v0")
    assert artifact.name == f"{job_name}:v0"


def test_artifact_job_creation(test_settings, runner, user, wandb_init):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write('print("test")')
        settings = test_settings()
        settings.update(
            {
                "disable_git": True,
                "program_relpath": "./blah/test_program.py",
            }
        )
        run = wandb_init(settings=settings)
        run.log_code()
        run.finish()
        api = public.Api()
        name = make_artifact_name_safe(
            f"job-source-uncategorized-{run._settings.program_relpath}"
        )
        artifact = api.artifact(f"{user}/uncategorized/{name}:v0")
        assert artifact.name == f"{name}:v0"


def test_container_job_creation(test_settings, user):
    settings = test_settings()
    settings.update({"disable_git": True})
    with mock.patch.dict("os.environ", WANDB_DOCKER="dummy-container:docker-tag"):
        run = wandb.init(settings=settings)
        run.finish()
        api = public.Api()
        artifact = api.artifact(f"{user}/uncategorized/job-dummy-container:docker-tag")
        assert artifact.name == "job-dummy-container:docker-tag"


"""Test internal APIs"""


def test_get_run_state(test_settings, user, wandb_init):
    run = wandb_init(entity=user, project="test")
    _api = internal.Api()
    res = _api.get_run_state(user, "test", run.id)
    run.finish()
    assert res == "running", "Test run must have state running"
