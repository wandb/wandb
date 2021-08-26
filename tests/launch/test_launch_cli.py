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
@pytest.mark.timeout(320)
def test_launch_agent_base(
    runner, test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    def patched_pop_from_queue(self, queue):
        ups = self._api.pop_from_run_queue(
            queue, entity=self._entity, project=self._project
        )
        if ups is None:
            raise KeyboardInterrupt
        return ups

    with runner.isolated_filesystem():
        monkeypatch.setattr(
            "wandb.sdk.launch.agent.LaunchAgent.pop_from_queue",
            lambda c, queue: patched_pop_from_queue(c, queue),
        )
        result = runner.invoke(cli.launch_agent, "test_project")
        assert result.exit_code == 0
        ctx = live_mock_server.get_ctx()
        assert ctx["num_popped"] == 1
        assert ctx["num_acked"] == 1
        assert "Shutting down, active jobs" in result.output


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.timeout(320)
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
        assert "python train.py --epochs 1" in result.output


@pytest.mark.timeout(320)
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
        assert "python train.py --epochs 1" in result.output


def test_launch_no_docker_exec(
    runner, monkeypatch, mocked_fetchable_git_repo, test_settings,
):
    monkeypatch.setattr(wandb.sdk.launch.docker, "find_executable", lambda name: False)
    result = runner.invoke(
        cli.launch, ["https://wandb.ai/mock_server_entity/test_project/runs/1"],
    )
    assert result.exit_code == 1
    assert "Could not find Docker executable" in str(result.exception)


@pytest.mark.timeout(320)
def test_launch_github_url(runner, mocked_fetchable_git_repo, live_mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            ["https://github.com/test/repo.git", "--entry-point", "train.py",],
        )
    assert result.exit_code == 0
    assert "Launching run in docker with command: docker run" in result.output
    assert "python train.py" in result.output


@pytest.mark.timeout(320)
def test_launch_local_dir(runner):
    with runner.isolated_filesystem():
        os.mkdir("repo")
        with open("repo/main.py", "w+") as f:
            f.write('print("ok")\n')
        result = runner.invoke(cli.launch, ["repo"],)

    assert result.exit_code == 0
    assert "Launching run in docker with command: docker run" in result.output
    assert "main.py" in result.output
