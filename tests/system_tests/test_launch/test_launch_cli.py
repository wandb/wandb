import json
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.errors import LaunchError

REPO_CONST = "test-repo"
IMAGE_CONST = "fake-image"
QUEUE_NAME = "test_queue"


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
            ["create", job_type, path, "--entity", user],
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


def test_launch_supplied_logfile(runner, monkeypatch, wandb_caplog, user):
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
        with wandb_caplog.at_level("INFO"):
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
        if not isinstance(args[3], dict) or args[3] != expected_template_variables:
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


def test_launch_from_uri_creates_job(
    runner,
    mocker,
    user,
):
    mock_job_artifact = MagicMock()
    mock_job_artifact.name = "test:latest"
    mock_create_job_function = MagicMock(return_value=(mock_job_artifact, None, None))
    mock_launch_function = AsyncMock()
    mocker.patch("wandb.sdk.launch._launch._launch", mock_launch_function)
    mocker.patch("wandb.sdk.launch.create_job._create_job", mock_create_job_function)

    result = "none"
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "--project",
                "test",
                "--uri",
                "https://github.com/test/test.git",
                "--entry-point",
                "python test.py",
                "--job-name",
                "test-job",
            ],
        )

    assert result.exit_code == 0
    mock_create_job_function.assert_called_once()
    mock_launch_function.assert_called_once()
    create_job_args = mock_create_job_function.call_args[0]
    launch_args = mock_launch_function.call_args[0]

    assert create_job_args[1] == "git"
    assert create_job_args[2] == "https://github.com/test/test.git"
    assert launch_args[1].endswith("/test/test:latest")
