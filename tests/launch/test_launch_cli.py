import wandb
from wandb.cli import cli
from wandb.apis.internal import InternalApi
import pytest
from tests import utils

from .test_launch import mocked_fetchable_git_repo


def test_launch(runner, test_settings, live_mock_server, mocked_fetchable_git_repo):
    pass


def test_launch_add_default(runner, test_settings, live_mock_server):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--project=test_project",
        "--entity=mock_server_entity",
    ]
    result = runner.invoke(cli.launch_add, args)
    assert result.exit_code == 0
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


def test_launch_add_config_file(runner, test_settings, live_mock_server):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--project=test_project",
        "--entity=mock_server_entity",
    ]
    result = runner.invoke(cli.launch_add, args)
    assert result.exit_code == 0
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


# this test includes building a docker container which can take some time.
# hence the timeout.
@pytest.mark.timeout(300)
def test_launch_agent_base(
    runner, test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):

    with runner.isolated_filesystem():
        monkeypatch.setattr(
            "wandb.sdk.launch.agent.LaunchAgent.pop_from_queue",
            lambda c, queue: try_this_out(c, queue),
        )
        result = runner.invoke(cli.launch_agent, "test_project")
        assert result.exit_code == 0
        ctx = live_mock_server.get_ctx()
        assert ctx["num_popped"] == 1
        assert ctx["num_acked"] == 1
        assert "Shutting down, active jobs" in result.output


def test_launch_no_docker_exec(
    runner, monkeypatch, mocked_fetchable_git_repo, test_settings,
):
    monkeypatch.setattr(wandb.sdk.launch.docker, "find_executable", lambda name: False)
    result = runner.invoke(
        cli.launch, ["https://wandb.ai/mock_server_entity/test_project/runs/1"],
    )
    assert result.exit_code == 1
    assert "Could not find Docker executable" in str(result.exception)


def try_this_out(self, queue):
    try:
        ups = self._api.pop_from_run_queue(
            queue, entity=self._entity, project=self._project
        )
        wandb.termlog("UPS {}".format(ups))
        if ups is None:
            wandb.termlog("UPS IS NONE {}".format(ups))
            raise KeyboardInterrupt
    except Exception as e:
        print("Exception:", e)
        return None
    return ups
