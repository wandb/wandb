import json
from unittest.mock import MagicMock, Mock

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.errors import LaunchError

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
        patched_launch_add,
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

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LaunchProject",
        lambda *args, **kwargs: MagicMock(),
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

    async def patched_launch(
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

        mock_run = Mock()
        rv = Mock()
        rv.state = "finished"

        async def _mock_get_status():
            return rv

        mock_run.get_status = _mock_get_status
        return mock_run

    monkeypatch.setattr(
        "wandb.sdk.launch._launch._launch",
        patched_launch,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch._launch.LaunchAgent",
        lambda *args, **kwargs: MagicMock(),
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

    monkeypatch.setattr(
        wandb.sdk.launch._project_spec,
        "LaunchProject",
        lambda *args, **kwargs: MagicMock(),
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
        lambda c, e, p, q, a, v, g: {"launchAgentId": "mock_agent_id"},
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
    async def pop_from_run_queue(self, queue):
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
        lambda c, run_queue_item_id, message, phase, files: print_then_exit(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.run_job",
        lambda a, b, c, d: raise_(LaunchError("blah blah")),
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


@pytest.mark.parametrize(
    "path,job_type",
    [
        ("./test.py", "code"),
        ("test.py", "code"),
    ],
)
def test_create_job_no_reqs(path, job_type, runner, user):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write("print('hello world')\n")

        result = runner.invoke(
            cli.job,
            ["create", job_type, path, "--entity", user, "--project", "proj"],
        )
        print(result.output)
        assert "Could not find requirements.txt file" in result.output


@pytest.mark.parametrize(
    "path,job_type",
    [
        ("./test.py", "123"),
        ("./test.py", ""),
        (".test.py", "docker"),
        (".test.py", "repo"),
    ],
)
def test_create_job_bad_type(path, job_type, runner, user):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write("print('hello world')\n")

        with open("requirements.txt", "w") as f:
            f.write("wandb\n")

        result = runner.invoke(
            cli.job,
            ["create", job_type, path, "--entity", user, "--project", "proj"],
        )
        print(result.output)
        assert (
            "ERROR" in result.output
            or "Usage: job create [OPTIONS] {git|code|image} PATH" in result.output
        )


def patched_run_run_entry(cmd, dir):
    print(f"running command: {cmd}")
    mock_run = Mock()
    rv = Mock()
    rv.state = "finished"

    async def _mock_get_status():
        return rv

    mock_run.get_status = _mock_get_status
    return mock_run


def test_launch_supplied_docker_image(
    runner,
    monkeypatch,
):
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image",
        lambda docker_image: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.docker_image_exists",
        lambda docker_image: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        patched_run_run_entry,
    )

    async def _mock_validate_docker_installation():
        pass

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        _mock_validate_docker_installation,
    )

    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "--async",
                "--docker-image",
                "test:tag",
            ],
        )

    print(result)
    assert result.exit_code == 0
    assert "-e WANDB_DOCKER=test:tag" in result.output
    assert " -e WANDB_CONFIG='{}'" in result.output
    assert "-e WANDB_ARTIFACTS='{}'" in result.output
    assert "test:tag" in result.output


def test_launch_supplied_logfile(
    runner, monkeypatch, caplog, wandb_init, test_settings
):
    """Test that the logfile is set properly when supplied via the CLI."""

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

    with runner.isolated_filesystem():
        with caplog.at_level("INFO"):
            result = runner.invoke(
                cli.launch_agent,
                [
                    "--queue=default",
                    "--log-file=agent.logs",
                ],
            )

            assert "Internal agent logs printing to agent.logs" in result.output

            print("Output from cli command:")
            print(result.output)

            # open agent logs and inspect the contents
            with open("agent.logs") as f:
                logs = f.read()
                print("agent.logs:")
                print(logs)
                assert "Internal agent logs printing to agent.logs" in logs

            assert result.exit_code == 0  # Do at the end so we get maximum printing


@pytest.mark.parametrize(
    "command_inputs,expected_error",
    [
        (
            [
                "--queue=default",
                "--set-var",
                "test_str=str1",
                "--set-var",
                "test_int=2",
                "--set-var",
                "test_num=2.5",
            ],
            None,
        ),
        (
            [
                "--queue=default",
                "--set-var",
                "test_str=str1",
                "--set-var",
                "test_int=2.5",
                "--set-var",
                "test_num=2.5",
            ],
            "Value for test_int must be of type integer.",
        ),
        (
            [
                "--queue=default",
                "--set-var",
                "test_str=str1",
                "--set-var",
                "test_int=2",
                "--set-var",
                "test_num=abc",
            ],
            "Value for test_num must be of type number.",
        ),
        (
            [
                "--queue=default",
                "--set-var",
                "illegal_override=3",
            ],
            "Queue test-queue does not support overriding illegal_override.",
        ),
        (
            [
                "--queue=default",
                "--set-var",
                "test_str=str1,test_int=2,test_num=2.5",
            ],
            '--set-var value must be in the format "--set-var key1=value1", instead got: test_str=str1,test_int=2,test_num=2.5',
        ),
    ],
)
def test_launch_template_vars(command_inputs, expected_error, runner, monkeypatch):
    mock_template_variables = [
        {"name": "test_str", "schema": json.dumps({"type": "string"})},
        {"name": "test_int", "schema": json.dumps({"type": "integer"})},
        {"name": "test_num", "schema": json.dumps({"type": "number"})},
    ]
    expected_template_variables = {"test_str": "str1", "test_int": 2, "test_num": 2.5}

    def patched_launch_add(*args, **kwargs):
        # Assert template variables are as expected
        if not isinstance(args[4], dict) or args[4] != expected_template_variables:
            raise Exception(args)

    monkeypatch.setattr(
        "wandb.cli.cli._launch_add",
        patched_launch_add,
    )

    def patched_public_api(*args, **kwargs):
        return Mock()

    monkeypatch.setattr(
        "wandb.cli.cli.PublicApi",
        patched_public_api,
    )

    monkeypatch.setattr("wandb.cli.cli.launch_utils.check_logged_in", lambda _: None)

    def patched_run_queue(*args, **kwargs):
        mock_rq = Mock()
        mock_rq.template_variables = mock_template_variables
        mock_rq.name = "test-queue"
        return mock_rq

    monkeypatch.setattr(
        "wandb.cli.cli.RunQueue",
        patched_run_queue,
    )

    result = "none"
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, command_inputs, catch_exceptions=False)
    if expected_error:
        assert expected_error in result.output
        assert result.exit_code == 1
    else:
        assert result.exit_code == 0
