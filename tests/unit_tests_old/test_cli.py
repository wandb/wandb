import json
import os
import platform
import subprocess
import traceback

import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.cli import cli


@pytest.fixture
def docker(request, mock_server, mocker, monkeypatch):
    wandb_args = {"check_output": b'["wandb/deepo@sha256:abc123"]'}
    marker = request.node.get_closest_marker("wandb_args")
    if marker:
        wandb_args.update(marker.kwargs)
    docker = mocker.MagicMock()
    api_key = mocker.patch(
        "wandb.apis.InternalApi.api_key", new_callable=mocker.PropertyMock
    )
    api_key.return_value = "test"
    monkeypatch.setattr(cli, "find_executable", lambda name: True)
    old_call = subprocess.call

    def new_call(command, **kwargs):
        if command[0] == "docker":
            return docker(command)
        else:
            return old_call(command, **kwargs)

    monkeypatch.setattr(subprocess, "call", new_call)

    monkeypatch.setattr(
        subprocess, "check_output", lambda *args, **kwargs: wandb_args["check_output"]
    )
    return docker


def test_artifact_download(runner, git_repo, mock_server):
    result = runner.invoke(cli.artifact, ["get", "test/mnist:v0"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Downloading dataset artifact" in result.output
    path = os.path.join(".", "artifacts", "mnist:v0")
    if platform.system() == "Windows":
        head, tail = os.path.splitdrive(path)
        path = head + tail.replace(":", "-")
    assert "Artifact downloaded to %s" % path in result.output
    assert os.path.exists(path)


def test_artifact_upload(runner, git_repo, mock_server, mocker, mocked_run):
    with open("artifact.txt", "w") as f:
        f.write("My Artifact")
    mocker.patch("wandb.init", lambda *args, **kwargs: mocked_run)
    result = runner.invoke(cli.artifact, ["put", "artifact.txt", "-n", "test/simple"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Uploading file artifact.txt to:" in result.output
    #  TODO: one of the tests above is setting entity to y
    assert "test/simple:v0" in result.output


def test_artifact_ls(runner, git_repo, mock_server):
    result = runner.invoke(cli.artifact, ["ls", "test"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "10.0KB" in result.output
    assert "mnist:v2" in result.output


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="The patch in mock_server.py doesn't work in windows",
)
def test_restore_no_remote(runner, mock_server, git_repo, docker, monkeypatch):
    # TODO(jhr): does not work with --flake-finder
    with open("patch.txt", "w") as f:
        f.write("test")
    git_repo.repo.index.add(["patch.txt"])
    git_repo.repo.commit()
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Created branch wandb/abcdef" in result.output
    assert "Applied patch" in result.output
    assert "Restored config variables to " in result.output
    assert "Launching docker container" in result.output
    docker.assert_called_with(
        [
            "docker",
            "run",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "WANDB_DOCKER=wandb/deepo@sha256:abc123",
            "--ipc=host",
            "-v",
            wandb.docker.entrypoint + ":/wandb-entrypoint.sh",
            "--entrypoint",
            "/wandb-entrypoint.sh",
            "-v",
            os.getcwd() + ":/app",
            "-w",
            "/app",
            "-e",
            "WANDB_API_KEY=test",
            "-e",
            "WANDB_COMMAND=python train.py --test foo",
            "-it",
            "test/docker",
            "/bin/bash",
        ]
    )


def test_restore_bad_remote(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates its own isolated filesystem
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    api = InternalApi({"project": "test"})
    monkeypatch.setattr(cli, "_api", api)

    def bad_commit(cmt):
        raise ValueError()

    monkeypatch.setattr(api.git.repo, "commit", bad_commit)
    monkeypatch.setattr(api, "download_urls", lambda *args, **kwargs: [])
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 1
    assert "Run `git clone http://fake.git/foo/bar`" in result.output


def test_restore_good_remote(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates its own isolated filesystem
    git_repo.repo.create_remote("origin", "git@fake.git:foo/bar")
    monkeypatch.setattr(subprocess, "check_call", lambda command: True)
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Created branch wandb/abcdef" in result.output


def test_restore_slashes(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates its own isolated filesystem
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["wandb/test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output


def test_restore_no_entity(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates its own isolated filesystem
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output


def test_restore_no_diff(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates its own isolated filesystem
    git_repo.repo.create_remote("origin", "git@fake.git:foo/bar")
    monkeypatch.setattr(subprocess, "check_call", lambda command: True)
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    mock_server.set_context("bucket_config", {"files": ["wandb-metadata.json"]})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Created branch wandb/abcdef" in result.output
    # no patching operations performed, whether successful or not
    assert "Applied patch" not in result.output
    assert "Filed to apply patch" not in result.output


def test_restore_not_git(runner, mock_server, docker, monkeypatch):
    with runner.isolated_filesystem():
        monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
        result = runner.invoke(cli.restore, ["test/abcdef"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Original run has no git history" in result.output


@pytest.mark.parametrize("stop_method", ["stop", "cancel"])
def test_sweep_pause(runner, mock_server, test_settings, stop_method):
    with runner.isolated_filesystem():
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)
        assert sweep_id == "test"
        assert runner.invoke(cli.sweep, ["--pause", sweep_id]).exit_code == 0
        assert runner.invoke(cli.sweep, ["--resume", sweep_id]).exit_code == 0
        if stop_method == "stop":
            assert runner.invoke(cli.sweep, ["--stop", sweep_id]).exit_code == 0
        else:
            assert runner.invoke(cli.sweep, ["--cancel", sweep_id]).exit_code == 0


def test_sweep_scheduler(runner, mock_server, test_settings):
    with runner.isolated_filesystem():
        with open("mock_launch_config.json", "w") as f:
            json.dump(
                {
                    "queue": "default",
                    "resource": "local-process",
                    "job": "mock-launch-job",
                    "scheduler": {
                        "resource": "local-process",
                    },
                },
                f,
            )
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)
        assert sweep_id == "test"
        assert (
            runner.invoke(
                cli.sweep,
                ["--launch_config", "mock_launch_config.json", sweep_id],
            ).exit_code
            == 0
        )
