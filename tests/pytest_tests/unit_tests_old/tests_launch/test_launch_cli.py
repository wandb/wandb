import json
import os

import pytest
import wandb
from wandb.cli import cli

from .test_launch import mock_load_backend, mocked_fetchable_git_repo  # noqa: F401


def raise_(ex):
    raise ex


@pytest.fixture
def kill_agent_on_update_job(monkeypatch):
    def patched_update_finished(self, job_id):
        if self._jobs[job_id].get_status().state in ["failed", "finished"]:
            self.finish_job_id(job_id)
            if self._running == 0:
                # only 1 run in test so kill after it's done
                raise KeyboardInterrupt

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent._update_finished",
        lambda c, job_id: patched_update_finished(c, job_id),
    )


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.flaky
@pytest.mark.xfail(reason="test goes through flaky periods. Re-enable with WB7616")
@pytest.mark.timeout(320)
def test_launch_agent_base(
    runner,
    test_settings,
    live_mock_server,
    mocked_fetchable_git_repo,
    kill_agent_on_update_job,
    monkeypatch,
):
    monkeypatch.setattr(
        wandb.sdk.launch.utils,
        "LAUNCH_CONFIG_FILE",
        os.path.join("./config/wandb/launch-config.yaml"),
    )
    launch_config = {"build": {"type": "docker"}, "registry": {"url": "test"}}

    with runner.isolated_filesystem():
        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump(launch_config, f)
        result = runner.invoke(cli.launch_agent, "test_project")
        ctx = live_mock_server.get_ctx()
        assert ctx["num_popped"] == 1
        assert ctx["num_acked"] == 1
        assert len(ctx["launch_agents"].keys()) == 1
        assert ctx["run_queues_return_default"] is True
        assert "Shutting down, active jobs" in result.output
        assert "polling on project" in result.output


def test_agent_queues_notfound(runner, test_settings, live_mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch_agent,
            [
                "--entity",
                "mock_server_entity",
                "--queue",
                "nonexistent_queue",
            ],
        )
        assert result.exit_code != 0
        assert "Not all of requested queues (nonexistent_queue) found" in result.output


def test_agent_queues_config(runner, test_settings, live_mock_server, monkeypatch):
    monkeypatch.setattr(
        wandb.sdk.launch.launch,
        "LAUNCH_CONFIG_FILE",
        os.path.join("./config/wandb/launch-config.yaml"),
    )
    launch_config = {"build": {"type": "docker"}, "queues": ["q1", "q2"]}

    with runner.isolated_filesystem():
        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump(launch_config, f)
        result = runner.invoke(
            cli.launch_agent,
            [
                "--entity",
                "mock_server_entity",
            ],
        )
        assert result.exit_code != 0
        assert "Not all of requested queues (q1, q2) found" in result.output


def test_agent_failed_default_create(runner, test_settings, live_mock_server):
    with runner.isolated_filesystem():
        live_mock_server.set_ctx({"successfully_create_default_queue": False})
        live_mock_server.set_ctx({"run_queues_return_default": False})
        result = runner.invoke(
            cli.launch_agent,
            [
                "--project",
                "test_project",
                "--entity",
                "mock_server_entity",
            ],
        )
        assert result.exit_code != 0


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
        "resource": "local-container",
        "overrides": {"args": ["--epochs", "5"]},
    }
    with runner.isolated_filesystem():
        with open("config.json", "w") as fp:
            json.dump(
                config,
                fp,
            )

        result = runner.invoke(
            cli.launch,
            [
                "-c",
                "config.json",
                "-u" "https://wandb.ai/mock_server_entity/test_project/runs/1",
            ],
        )
        assert result.exit_code == 0
        assert "Launching run in docker with command: docker run" in result.output


@pytest.mark.timeout(320)
def test_launch_cli_with_config_and_params(
    runner, mocked_fetchable_git_repo, live_mock_server
):
    config = {
        "uri": "https://wandb.ai/mock_server_entity/test_project/runs/1",
        "project": "test_project",
        "entity": "mock_server_entity",
        "resource": "local-container",
        "overrides": {"args": ["--epochs", "5"]},
    }
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "-c",
                json.dumps(config),
                "-u",
                "https://wandb.ai/mock_server_entity/test_project/runs/1",
            ],
        )
        assert result.exit_code == 0
        assert "Launching run in docker with command: docker run" in result.output


def test_launch_no_docker_exec(
    runner,
    monkeypatch,
    mocked_fetchable_git_repo,
    test_settings,
):
    monkeypatch.setattr(
        wandb.sdk.launch.builder.build, "find_executable", lambda name: False
    )
    result = runner.invoke(
        cli.launch,
        ["-u", "https://wandb.ai/mock_server_entity/test_project/runs/1"],
    )
    assert result.exit_code == 1
    assert "Could not find Docker executable" in str(result.exception)


def test_sweep_launch_scheduler(runner, test_settings, live_mock_server):
    with runner.isolated_filesystem():
        with open("sweep-config.yaml", "w") as f:
            json.dump(
                {
                    "name": "My Sweep",
                    "method": "grid",
                    "job": "test-job:v9",
                    "launch": {
                        "queue": "default",
                        "resource": "local-process",
                    },
                    "scheduler": {
                        "resource": "local-process",
                    },
                    "parameters": {"parameter1": {"values": [1, 2, 3]}},
                },
                f,
            )
        result = runner.invoke(
            cli.launch_sweep,
            [
                "sweep-config.yaml",
                "--entity",
                "mock_server_entity",
            ],
        )
        assert result.exit_code == 0


@pytest.mark.timeout(320)
def test_launch_github_url(runner, mocked_fetchable_git_repo, live_mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "-u",
                "https://github.com/test/repo.git",
                "--entry-point",
                "python train.py",
            ],
        )
    print(result)
    assert result.exit_code == 0

    assert "Launching run in docker with command: docker run" in result.output


@pytest.mark.timeout(320)
def test_launch_local_dir(runner, live_mock_server):
    with runner.isolated_filesystem():
        os.mkdir("repo")
        with open("repo/main.py", "w+") as f:
            f.write('print("ok")\n')
        with open("repo/requirements.txt", "w+") as f:
            f.write("wandb\n")
        result = runner.invoke(
            cli.launch,
            ["-u", "repo"],
        )

    assert result.exit_code == 0
    assert "Launching run in docker with command: docker run" in result.output


def test_launch_queue_error(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.launch,
            [
                "-u",
                "https://github.com/test/repo.git",
                "--entry-point",
                "train.py",
                "--async",
                "--queue",
                "default",
            ],
        )

    assert result.exit_code != 0
    assert "Cannot use both --async and --queue with wandb launch" in result.output


def test_launch_supplied_docker_image(
    runner,
    monkeypatch,
    live_mock_server,
):
    def patched_run_run_entry(cmd, dir):
        print(f"running command: {cmd}")
        return cmd  # noop

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image",
        lambda docker_image: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        patched_run_run_entry,
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


def test_launch_agent_project_environment_variable(
    runner,
    test_settings,
    live_mock_server,
    monkeypatch,
):
    monkeypatch.setenv("WANDB_PROJECT", "test_project")
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.run_job",
        lambda a, b: raise_(KeyboardInterrupt),
    )
    result = runner.invoke(cli.launch_agent)
    assert (
        "You must specify a project name or set WANDB_PROJECT environment variable."
        not in str(result.output)
    )


def test_launch_name_run_id_environment_variable(
    runner,
    mocked_fetchable_git_repo,
    live_mock_server,
):
    run_id = "test_run_id"
    run_name = "test_run_name"
    args = [
        "-u",
        "https://github.com/test/repo.git",
        "--entry-point",
        "train.py",
        "-c",
        json.dumps({"run_id": run_id}),
        "--name",
        run_name,
    ]
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args)

    assert f"WANDB_RUN_ID={run_id}" in str(result.output)
    assert f"WANDB_NAME={run_name}" in str(result.output)
