import json
import os

import wandb
from wandb.cli import cli
from wandb.apis.internal import InternalApi
import pytest
from tests import utils

from .test_launch import mocked_fetchable_git_repo, mock_load_backend  # noqa: F401


def test_launch(runner, test_settings, live_mock_server, mocked_fetchable_git_repo):
    pass


def test_launch_add_default(runner, test_settings, live_mock_server):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--project=test_project",
        "--entity=mock_server_entity",
        "--queue",
    ]
    result = runner.invoke(cli.launch, args)
    assert result.exit_code == 0
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


def test_launch_add_config_file(runner, test_settings, live_mock_server):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--project=test_project",
        "--entity=mock_server_entity",
        "--queue",
    ]
    result = runner.invoke(cli.launch, args)
    assert result.exit_code == 0
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.flaky
@pytest.mark.xfail(reason="test goes through flaky periods. Re-enable with WB7616")
@pytest.mark.timeout(400)
def test_launch_agent_base(
    runner, test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    def patched_update_finished(self, job_id):
        if self._jobs[job_id].get_status().state in ["failed", "finished"]:
            self.finish_job_id(job_id)
            if self._running == 0:
                # only 1 run in test so kill after it's done
                raise KeyboardInterrupt

    with runner.isolated_filesystem():
        monkeypatch.setattr(
            "wandb.sdk.launch.agent.LaunchAgent._update_finished",
            lambda c, job_id: patched_update_finished(c, job_id),
        )
        result = runner.invoke(cli.launch_agent, "test_project")
        ctx = live_mock_server.get_ctx()
        assert ctx["num_popped"] == 1
        assert ctx["num_acked"] == 1
        assert len(ctx["launch_agents"].keys()) == 1
        assert ctx["run_queues_return_default"] == True
        assert "Shutting down, active jobs" in result.output
        assert "polling on project" in result.output


def test_agent_queues_notfound(runner, test_settings, live_mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch_agent,
            [
                "test_project",
                "--entity",
                "mock_server_entity",
                "--queues",
                "nonexistent_queue",
            ],
        )
        assert result.exit_code != 0
        assert "Not all of requested queues (nonexistent_queue) found" in result.output


def test_agent_failed_default_create(runner, test_settings, live_mock_server):
    with runner.isolated_filesystem():
        live_mock_server.set_ctx({"successfully_create_default_queue": False})
        live_mock_server.set_ctx({"run_queues_return_default": False})
        result = runner.invoke(
            cli.launch_agent, ["test_project", "--entity", "mock_server_entity",],
        )
        assert result.exit_code != 0


def test_agent_update_failed(runner, test_settings, live_mock_server):
    live_mock_server.set_ctx({"launch_agent_update_fail": True})
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch_agent, ["test_project", "--entity", "mock_server_entity",],
        )

        assert "Failed to update agent status" in result.output


def test_agent_stop_polling(runner, live_mock_server, monkeypatch):
    def patched_pop_empty_queue(self, queue):
        # patch to no result, agent should read stopPolling and stop
        return None

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.pop_from_queue",
        lambda c, queue: patched_pop_empty_queue(c, queue),
    )
    live_mock_server.set_ctx({"stop_launch_agent": True})
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch_agent, ["test_project", "--entity", "mock_server_entity",],
        )

    assert "Shutting down, active jobs" in result.output


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.timeout(400)
def test_launch_cli_with_config_file_and_params(
    runner, mocked_fetchable_git_repo, live_mock_server
):
    config = {
        "uri": "https://wandb.ai/mock_server_entity/test_project/runs/1",
        "project": "test_project",
        "entity": "mock_server_entity",
        "resource": "local",
        "overrides": {"args": ["--epochs", "5"]},
    }
    with runner.isolated_filesystem():
        with open("config.json", "w") as fp:
            json.dump(
                config, fp,
            )

        result = runner.invoke(
            cli.launch,
            [
                "-c",
                "config.json",
                "-a",
                "epochs=1",
                "https://wandb.ai/mock_server_entity/test_project/runs/1",
            ],
        )
        assert result.exit_code == 0
        assert "Launching run in docker with command: docker run" in result.output


@pytest.mark.timeout(400)
def test_launch_cli_with_config_and_params(
    runner, mocked_fetchable_git_repo, live_mock_server
):
    config = {
        "uri": "https://wandb.ai/mock_server_entity/test_project/runs/1",
        "project": "test_project",
        "entity": "mock_server_entity",
        "resource": "local",
        "overrides": {"args": ["--epochs", "5"]},
    }
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "-c",
                json.dumps(config),
                "-a",
                "epochs=1",
                "https://wandb.ai/mock_server_entity/test_project/runs/1",
            ],
        )
        assert result.exit_code == 0
        assert "Launching run in docker with command: docker run" in result.output


def test_launch_no_docker_exec(
    runner, monkeypatch, mocked_fetchable_git_repo, test_settings,
):
    monkeypatch.setattr(wandb.sdk.launch.docker, "find_executable", lambda name: False)
    result = runner.invoke(
        cli.launch, ["https://wandb.ai/mock_server_entity/test_project/runs/1"],
    )
    assert result.exit_code == 1
    assert "Could not find Docker executable" in str(result.exception)


@pytest.mark.timeout(400)
def test_launch_github_url(runner, mocked_fetchable_git_repo, live_mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            ["https://github.com/test/repo.git", "--entry-point", "train.py",],
        )
    assert result.exit_code == 0
    assert "Launching run in docker with command: docker run" in result.output


@pytest.mark.timeout(400)
def test_launch_local_dir(runner):
    with runner.isolated_filesystem():
        os.mkdir("repo")
        with open("repo/main.py", "w+") as f:
            f.write('print("ok")\n')
        with open("repo/requirements.txt", "w+") as f:
            f.write("wandb\n")
        result = runner.invoke(cli.launch, ["repo"],)

    assert result.exit_code == 0
    assert "Launching run in docker with command: docker run" in result.output


def test_launch_queue_error(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "https://github.com/test/repo.git",
                "--entry-point",
                "train.py",
                "--async",
                "--queue",
            ],
        )

    assert result.exit_code != 0
    assert "Cannot use both --async and --queue with wandb launch" in result.output


def test_launch_supplied_docker_image(
    runner, monkeypatch, live_mock_server,
):
    def patched_run_run_entry(cmd, dir):
        print(f"running command: {cmd}")
        return cmd  # noop

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local.pull_docker_image", lambda docker_image: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local._run_entry_point", patched_run_run_entry,
    )
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, ["--async", "--docker-image", "test:tag",],)

    assert result.exit_code == 0
    assert "-e WANDB_DOCKER=test:tag" in result.output
    assert " -e WANDB_CONFIG='{}'" in result.output
    assert "-e WANDB_ARTIFACTS='{}'" in result.output
    assert "test:tag" in result.output


@pytest.mark.timeout(400)
def test_launch_cuda_flag(runner, live_mock_server, mocked_fetchable_git_repo):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--entry-point",
        "train.py",
    ]
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args + ["--cuda"],)
    assert result.exit_code == 0

    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args + ["--cuda", "False"],)
    assert result.exit_code == 0

    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args + ["--cuda", "asdf"],)
    assert result.exit_code != 0
    assert "Invalid value for --cuda:" in result.output
