import json
from unittest import mock

import wandb
from wandb.apis import internal, public
from wandb.sdk.artifacts._internal_artifact import InternalArtifact
from wandb.sdk.internal import job_builder
from wandb.sdk.launch._project_spec import _inject_wandb_config_env_vars
from wandb.util import make_artifact_name_safe


def test_run_use_job_env_var(runner, wandb_backend_spy, user):
    art_name = "job-my-test-image"
    artifact_name = f"{user}/uncategorized/{art_name}"
    artifact_env = json.dumps({"_wandb_job": f"{artifact_name}:latest"})
    with (
        runner.isolated_filesystem(),
        mock.patch.dict("os.environ", WANDB_ARTIFACTS=artifact_env),
    ):
        artifact = InternalArtifact(name=art_name, type=job_builder.JOB_ARTIFACT_TYPE)
        filename = "file1.txt"
        with open(filename, "w") as fp:
            fp.write("hello!")
        artifact.add_file(filename)
        with wandb.init(entity=user) as run:
            run.log_artifact(artifact)
            artifact.wait()

        gql = wandb_backend_spy.gql
        create_artifact_spy = gql.Capture()
        use_artifact_spy = gql.Capture()
        wandb_backend_spy.stub_gql(
            gql.Matcher(operation="CreateArtifact"),
            create_artifact_spy,
        )
        wandb_backend_spy.stub_gql(
            gql.Matcher(operation="UseArtifact"),
            use_artifact_spy,
        )

        with wandb.init(entity=user, settings=wandb.Settings(launch=True)) as run:
            run.log({"x": 2})

        assert create_artifact_spy.total_calls == 0
        assert use_artifact_spy.total_calls == 1


def test_run_in_launch_context_with_multi_config_env_var(runner, monkeypatch, user):
    with runner.isolated_filesystem():
        config_env_vars = {}
        _inject_wandb_config_env_vars({"epochs": 10}, config_env_vars, 5)
        for k in config_env_vars:
            monkeypatch.setenv(k, config_env_vars[k])
        settings = wandb.Settings(launch=True)
        run = wandb.init(settings=settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        assert run.config.epochs == 10
        assert run.config.lr == 0.004


def test_run_in_launch_context_with_malformed_env_vars(
    runner, monkeypatch, capsys, user
):
    with runner.isolated_filesystem():
        monkeypatch.setenv("WANDB_ARTIFACTS", '{"epochs: 6}')
        monkeypatch.setenv("WANDB_CONFIG", '{"old_name": {"name": "test:v0"')
        settings = wandb.Settings(launch=True)
        run = wandb.init(settings=settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        _, err = capsys.readouterr()
        assert "Malformed WANDB_CONFIG, using original config" in err
        assert "Malformed WANDB_ARTIFACTS, using original artifacts" in err


def test_repo_job_creation(user):
    settings = wandb.Settings(
        program_relpath="./blah/test_program.py",
        git_remote_url="https://github.com/test/repo",
        git_commit="asdasdasdasd",
        disable_job_creation=False,
    )
    with wandb.init(settings=settings) as run:
        run.log({"test": 1})
    api = public.Api()
    job_name = make_artifact_name_safe(
        f"job-{run._settings.git_remote_url}_{run._settings.program_relpath}"
    )
    artifact = api.artifact(f"{user}/{run._settings.project}/{job_name}:v0")
    assert artifact.name == f"{job_name}:v0"


def test_artifact_job_creation(runner, user):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write('print("test")')
        settings = wandb.Settings(
            disable_git=True,
            program_relpath="./blah/test_program.py",
            disable_job_creation=False,
        )
        run = wandb.init(settings=settings)
        run.log_code()
        run.finish()
        api = public.Api()
        name = make_artifact_name_safe(
            f"job-source-uncategorized-{run._settings.program_relpath}"
        )
        artifact = api.artifact(f"{user}/uncategorized/{name}:v0")
        assert artifact.name == f"{name}:v0"


def test_container_job_creation(user):
    settings = wandb.Settings(disable_git=True, disable_job_creation=False)
    with mock.patch.dict("os.environ", WANDB_DOCKER="dummy-container:docker-tag"):
        run = wandb.init(settings=settings)
        run.finish()
        api = public.Api()
        artifact = api.artifact(f"{user}/uncategorized/job-dummy-container:docker-tag")
        assert artifact.name == "job-dummy-container:docker-tag"


"""Test internal APIs"""


def test_get_run_state(user):
    run = wandb.init(entity=user, project="test")
    _api = internal.Api()
    res = _api.get_run_state(user, "test", run.id)
    run.finish()
    assert res == "running", "Test run must have state running"
