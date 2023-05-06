import json

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.utils import LaunchError

REPO_CONST = "test-repo"
IMAGE_CONST = "fake-image"
QUEUE_NAME = "test_queue"


def _setup(mocker):
    pass


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
        "-u",
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
        "-u",
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
        "-u",
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
        resource_args,
        launch_config,
        synchronous,
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
        "-u",
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


def test_launch_build_with_local(
    relay_server,
    user,
    monkeypatch,
    runner,
):
    base_args = [
        "-u",
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
        "--build",
        "--queue=default",
        "--resource=local-process",
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
        result = runner.invoke(cli.launch, base_args)
        print(result.output)
        assert result.exit_code == 1
        assert (
            "Cannot build a docker image for the resource: local-process"
            in result.output
        )


def _setup_agent(monkeypatch, pop_func):
    monkeypatch.setattr("wandb.sdk.launch.agent.LaunchAgent.pop_from_queue", pop_func)

    monkeypatch.setattr(
        "wandb.init", lambda project, entity, settings, id, job_type: None
    )

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.create_launch_agent",
        lambda c, e, p, q, g: {"launchAgentId": "mock_agent_id"},
    )


def test_agent_stop_polling(runner, monkeypatch, user, test_settings):
    def patched_pop_empty_queue(self, queue):
        # patch to no result, agent should read stopPolling and stop
        return None

    _setup_agent(monkeypatch, patched_pop_empty_queue)

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.get_launch_agent",
        lambda c, i, g: {"id": "mock_agent_id", "name": "blah", "stopPolling": True},
    )
    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.update_launch_agent_status",
        lambda c, i, s, g: {"success": True},
    )

    args = ["--entity", user, "--queue", "default"]
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch_agent, args)

    assert "Shutting down, active jobs" in result.output


def raise_(ex):
    raise ex


def test_agent_update_failed(runner, monkeypatch, user, test_settings):
    args = ["--entity", user, "--queue", "default"]

    def patched_pop_empty_queue(self, queue):
        # patch to no result, agent should read stopPolling and stop
        raise_(KeyboardInterrupt)

    _setup_agent(monkeypatch, patched_pop_empty_queue)

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.get_launch_agent",
        lambda c, i, g: {"id": "mock_agent_id", "name": "blah", "stopPolling": False},
    )
    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.update_launch_agent_status",
        lambda c, i, s, g: {"success": False},
    )

    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch_agent, args)

        assert "Failed to update agent status" in result.output


def test_launch_agent_launch_error_continue(runner, monkeypatch, user, test_settings):
    def pop_from_run_queue(self, queue):
        return {
            "runSpec": {"job": "fake-job:latest"},
            "runQueueItemId": "fakerqi",
        }

    _setup_agent(monkeypatch, pop_from_run_queue)

    def print_then_exit():
        print("except caught, failed item")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.fail_run_queue_item",
        lambda c, r: print_then_exit(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.run_job",
        lambda a, b: raise_(LaunchError("blah blah")),
    )

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.get_launch_agent",
        lambda c, i, g: {"id": "mock_agent_id", "name": "blah", "stopPolling": False},
    )

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.update_launch_agent_status",
        lambda c, i, s, g: {"success": True},
    )

    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch_agent,
            [
                "--entity",
                user,
                "--queue",
                "default",
            ],
        )
        print(result.output)
        assert "blah blah" in result.output
        assert "except caught, failed item" in result.output
