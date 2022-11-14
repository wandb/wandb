import json

import pytest
import wandb
from wandb.cli import cli

REPO_CONST = "test-repo"
IMAGE_CONST = "fake-image"
QUEUE_NAME = "test_queue"


@pytest.mark.timeout(200)
@pytest.mark.parametrize(
    "args,override_config",
    [
        (
            ["--build", "--queue", QUEUE_NAME],
            {"registry": {"url": REPO_CONST}},
        ),
        (
            ["--queue", "--build", "--repository", REPO_CONST],
            {
                "registry": {"url": "testing123"},
                "docker": {"args": ["--container_arg", "9-rams"]},
            },
        ),
    ],
    ids=[
        "queue default build",
        "repository and docker args override",
    ],
)
def test_launch_build_succeeds(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
    override_config,
):
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
        "-c",
        json.dumps(override_config),
    ]

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    def patched_launch_add(*args, **kwargs):
        if not kwargs.get("build"):
            raise Exception(kwargs)

        if "--repository" in args:
            if not kwargs.get("repository"):
                raise Exception(kwargs)

        if args[3]:  # config
            assert args[3] == override_config

    monkeypatch.setattr(
        "wandb.cli.cli._launch_add",
        lambda *args, **kwargs: patched_launch_add(*args, **kwargs),
    )

    with runner.isolated_filesystem(), relay_server():
        result = runner.invoke(cli.launch, base_args + args)

        assert result.exit_code == 0


@pytest.mark.timeout(100)
@pytest.mark.parametrize(
    "args",
    [(["--build"]), (["--build=builder"])],
    ids=["no queue flag", "builder argument"],
)
def test_launch_build_fails(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
):
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
    ]

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    def patched_fetch_and_val(launch_project, _):
        return launch_project

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    monkeypatch.setattr(
        "wandb.docker",
        lambda: "docker",
    )

    with runner.isolated_filesystem(), relay_server():
        result = runner.invoke(cli.launch, base_args + args)

        if args == ["--build"]:
            assert result.exit_code == 1
            assert "Build flag requires a queue to be set" in result.output
        elif args == ["--build=builder"]:
            assert result.exit_code == 2
            assert (
                "Option '--build' does not take a value" in result.output
                or "Error: --build option does not take a value" in result.output
            )


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "args",
    [
        (["--repository=test_repo", "--resource=local"]),
        (["--repository="]),
        (["--repository"]),
    ],
    ids=["set repository", "set repository empty", "set repository empty2"],
)
def test_launch_repository_arg(
    relay_server,
    monkeypatch,
    runner,
    args,
    user,
    wandb_init,
    test_settings,
):
    base_args = [
        "https://github.com/wandb/examples",
        "--entity",
        user,
    ]

    def patched_run(
        uri,
        job,
        api,
        name,
        project,
        entity,
        docker_image,
        resource,
        entry_point,
        version,
        parameters,
        resource_args,
        launch_config,
        synchronous,
        cuda,
        run_id,
        repository,
    ):
        assert repository or "--repository=" in args or "--repository" in args

        return "run"

    monkeypatch.setattr(
        "wandb.sdk.launch.launch._run",
        lambda *args, **kwargs: patched_run(*args, **kwargs),
    )

    def patched_fetch_and_val(launch_project, _):
        return launch_project

    monkeypatch.setattr(
        "wandb.sdk.launch.launch.fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        "wandb.docker",
        lambda: "testing",
    )

    with runner.isolated_filesystem(), relay_server():
        result = runner.invoke(cli.launch, base_args + args)

        if "--respository=" in args or "--repository" in args:  # incorrect param
            assert result.exit_code == 2
        else:
            assert result.exit_code == 0


def test_launch_bad_api_key(runner, monkeypatch, user):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--entity",
        user,
        "--queue=default",
    ]
    monkeypatch.setenv("WANDB_API_KEY", "4" * 40)
    monkeypatch.setattr("wandb.sdk.internal.internal_api.Api.viewer", lambda a: False)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args)

        assert "Could not connect with current API-key." in result.output
