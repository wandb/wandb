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
