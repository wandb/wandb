import getpass
import importlib
import netrc
import os
import subprocess
import time
import traceback
from unittest import mock

import pytest
import wandb
import wandb.docker
from wandb import env
from wandb.cli import cli
from wandb.sdk import wandb_setup
from wandb.sdk.lib import config_util

DOCKER_SHA = (
    "wandb/deepo@sha256:"
    "3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177"
)


@pytest.fixture
def docker(request, mocker, monkeypatch):
    wandb_args = {"check_output": b'["wandb/deepo@sha256:abc123"]'}
    marker = request.node.get_closest_marker("wandb_args")
    if marker:
        wandb_args.update(marker.kwargs)
    docker = mocker.MagicMock()
    mocker.patch("wandb.cli.cli._configured_api_key", return_value="test")
    monkeypatch.setattr(cli, "_HAS_NVIDIA_DOCKER", True)
    monkeypatch.setattr(cli, "_HAS_DOCKER", True)
    old_call = subprocess.call

    def new_call(command, **kwargs):
        if command[0] == "docker":
            return docker(command, **kwargs)
        else:
            return old_call(command, **kwargs)

    monkeypatch.setattr(subprocess, "call", new_call)

    monkeypatch.setattr(
        subprocess, "check_output", lambda *args, **kwargs: wandb_args["check_output"]
    )
    return docker


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet:
        @property
        def hosts(self):
            return {"api.wandb.ai": None}

    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@pytest.mark.skip(reason="Currently dont have on in cling")
def test_enable_on(runner, git_repo):
    with runner.isolated_filesystem():
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject=rad")
        result = runner.invoke(cli.on)
        assert "W&B enabled" in str(result.output)
        assert result.exit_code == 0


@pytest.mark.skip(reason="Currently dont have off in cling")
def test_enable_off(runner, git_repo):
    with runner.isolated_filesystem():
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject=rad")
        result = runner.invoke(cli.off)
        assert "W&B disabled" in str(result.output)
        assert "disabled" in open("wandb/settings").read()
        assert result.exit_code == 0


def test_no_project_bad_command(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.cli, ["fsd"])
        assert "No such command" in result.output
        assert result.exit_code == 2


@pytest.mark.usefixtures("skip_verify_login")
def test_projects_with_sagemaker_credentials(runner, monkeypatch, mocker):
    monkeypatch.setenv("SM_TRAINING_ENV", "{}")
    with open("secrets.env", "w") as f:
        f.write(f"WANDB_API_KEY={'sagemaker' * 5}\n")
    mocker.patch.object(wandb.Api, "projects", return_value=[])

    result = runner.invoke(cli.projects, ["--entity", "example"])

    assert result.exit_code == 0, result.output
    assert "No projects found for example" in result.output


@pytest.fixture
def cli_run(mocker, patch_apikey):
    mocker.patch("wandb.sdk.wandb_login._verify_login")
    run_class = mocker.patch("wandb.apis.public.Run")
    run = run_class.return_value
    run.id = "run-id"
    run.project = "configured-project"
    run.commit = None
    run.rawconfig = {}
    run.metadata = {}
    file = mocker.Mock()
    file.name = "file.txt"
    run.files.side_effect = lambda names=None: [] if names else [file]
    return run_class


@pytest.mark.parametrize("command", [cli.pull, cli.restore])
@pytest.mark.parametrize(
    "path, expected",
    [
        ("run-id", ("option-entity", "configured-project", "run-id")),
        ("path-project/run-id", ("option-entity", "path-project", "run-id")),
        ("path-project:run-id", ("option-entity", "path-project", "run-id")),
        (
            "path-entity/path-project/run-id",
            ("path-entity", "path-project", "run-id"),
        ),
    ],
)
def test_run_commands_resolve_path(
    runner, cli_run, monkeypatch, command, path, expected
):
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    wandb_setup.singleton().settings.project = "configured-project"
    args = ["--entity", "option-entity", path]
    if command is cli.restore:
        args.insert(0, "--no-git")

    result = runner.invoke(command, args)

    assert result.exit_code == 0, result.output
    assert cli_run.call_args.args[1:] == expected


def test_restore_config_can_be_loaded(runner, cli_run, tmp_path, monkeypatch):
    config = {"epochs": 10, "layers": [32, 64], "nested": {"value": "original"}}
    cli_run.return_value.rawconfig = {**config, "_wandb": {}, "wandb_version": 1}
    monkeypatch.setattr(cli, "_get_wandb_dir", lambda: str(tmp_path / "wandb"))

    result = runner.invoke(cli.restore, ["--no-git", "entity/project/run-id"])

    assert result.exit_code == 0, result.output
    assert config_util.dict_from_config_file(tmp_path / "wandb/config.yaml") == config


@pytest.mark.parametrize(
    "host, error",
    [
        ("https://app.wandb.ai", "did you mean https://api.wandb.ai"),
        ("ftp://google.com", "URL scheme should be 'http' or 'https'"),
    ],
)
def test_login_bad_host(runner, host, error, local_settings):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, ["--host", host])
        assert error in str(result.exception)
        assert result.exit_code != 0


def test_login_invalid_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        invalid_key = "test-" + dummy_api_key[:-5]
        result = runner.invoke(cli.login, [invalid_key])
        assert "API key must have 40+ characters, has 35." in result.output


def test_docker_run_digest(runner, docker, monkeypatch):
    result = runner.invoke(
        cli.docker_run,
        [DOCKER_SHA],
    )
    assert result.exit_code == 0
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "WANDB_API_KEY",
            "-e",
            f"WANDB_DOCKER={DOCKER_SHA}",
            "--runtime",
            "nvidia",
            f"{DOCKER_SHA}",
        ],
        env=mock.ANY,
    )


def test_docker_run_bad_image(runner, docker, monkeypatch):
    result = runner.invoke(cli.docker_run, ["wandb///foo$"])
    assert result.exit_code == 0
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "WANDB_API_KEY",
            "--runtime",
            "nvidia",
            "wandb///foo$",
        ],
        env=mock.ANY,
    )


def test_docker_run_no_nvidia(runner, docker, monkeypatch):
    monkeypatch.setattr(cli, "_HAS_NVIDIA_DOCKER", False)
    result = runner.invoke(cli.docker_run, ["run", "-v", "cool:/cool", "rad"])
    assert result.exit_code == 0
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "WANDB_API_KEY",
            "-e",
            "WANDB_DOCKER=wandb/deepo@sha256:abc123",
            "-v",
            "cool:/cool",
            "rad",
        ],
        env=mock.ANY,
    )


def test_docker_run_nvidia(runner, docker):
    result = runner.invoke(
        cli.docker_run, ["run", "-v", "cool:/cool", "rad", "/bin/bash", "cool"]
    )
    assert result.exit_code == 0
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "WANDB_API_KEY",
            "-e",
            "WANDB_DOCKER=wandb/deepo@sha256:abc123",
            "--runtime",
            "nvidia",
            "-v",
            "cool:/cool",
            "rad",
            "/bin/bash",
            "cool",
        ],
        env=mock.ANY,
    )


def test_docker_run_api_key_not_in_args(runner, docker, mocker, monkeypatch):
    mocker.patch("wandb.cli.cli._configured_api_key", return_value="fake-api-key")
    monkeypatch.setenv("DOCKER_HOST", "tcp://localhost:2375")

    result = runner.invoke(cli.docker_run, ["rad"])

    assert result.exit_code == 0
    command = docker.call_args.args[0]
    assert "WANDB_API_KEY" in command
    assert not any("fake-api-key" in arg for arg in command)
    env = docker.call_args.kwargs["env"]
    assert env["WANDB_API_KEY"] == "fake-api-key"
    assert env["DOCKER_HOST"] == "tcp://localhost:2375"


def test_docker(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test"], input="n")
        docker.assert_called_once_with(
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
                "WANDB_API_KEY",
                "-it",
                "test",
                "/bin/bash",
            ],
            env=mock.ANY,
        )
        assert result.exit_code == 0


def test_docker_basic(runner, docker, git_repo):
    result = runner.invoke(cli.docker, ["test:abc123"], input="n")
    assert "Launching docker container" in result.output
    docker.assert_called_once_with(
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
            "WANDB_API_KEY",
            "-it",
            "test:abc123",
            "/bin/bash",
        ],
        env=mock.ANY,
    )
    assert result.exit_code == 0


def test_docker_sha(runner, docker):
    result = runner.invoke(cli.docker, ["test@sha256:abc123"], input="n")
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "WANDB_DOCKER=test@sha256:abc123",
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
            "WANDB_API_KEY",
            "-it",
            "test@sha256:abc123",
            "/bin/bash",
        ],
        env=mock.ANY,
    )
    assert result.exit_code == 0


def test_docker_no_dir(runner, docker):
    result = runner.invoke(cli.docker, ["test:abc123", "--no-dir"], input="n")
    docker.assert_called_once_with(
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
            "-e",
            "WANDB_API_KEY",
            "-it",
            "test:abc123",
            "/bin/bash",
        ],
        env=mock.ANY,
    )
    assert result.exit_code == 0


def test_docker_no_interactive_custom_command(runner, docker, git_repo):
    result = runner.invoke(
        cli.docker,
        ["test:abc123", "--no-tty", "--cmd", "python foo.py"],
        input="n",
    )
    docker.assert_called_once_with(
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
            "WANDB_API_KEY",
            "test:abc123",
            "/bin/bash",
            "-c",
            "python foo.py",
        ],
        env=mock.ANY,
    )
    assert result.exit_code == 0


def test_docker_jupyter(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "--jupyter"], input="n")
        docker.assert_called_once_with(
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
                "WANDB_API_KEY",
                "-e",
                "WANDB_ENSURE_JUPYTER=1",
                "-p",
                "8888:8888",
                "test",
                "/bin/bash",
                "-c",
                (
                    "jupyter lab --no-browser --ip=0.0.0.0 --allow-root "
                    "--NotebookApp.token= --notebook-dir /app"
                ),
            ],
            env=mock.ANY,
        )
        assert result.exit_code == 0


def test_docker_args(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "-v", "/tmp:/tmp"], input="n")
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
                "WANDB_API_KEY",
                "test",
                "-v",
                "/tmp:/tmp",
                "-it",
                "wandb/deepo:all-cpu",
                "/bin/bash",
            ],
            env=mock.ANY,
        )
        assert result.exit_code == 0


def test_docker_api_key_not_in_args(runner, docker, mocker, monkeypatch):
    mocker.patch("wandb.cli.cli._configured_api_key", return_value="fake-api-key")
    monkeypatch.setenv("DOCKER_HOST", "tcp://localhost:2375")

    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test"], input="n")

    assert result.exit_code == 0
    command = docker.call_args.args[0]
    assert "WANDB_API_KEY" in command
    assert not any("fake-api-key" in arg for arg in command)
    env = docker.call_args.kwargs["env"]
    assert env["WANDB_API_KEY"] == "fake-api-key"
    assert env["DOCKER_HOST"] == "tcp://localhost:2375"


def test_docker_digest(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "--digest"])
        assert result.output == "wandb/deepo@sha256:abc123"
        assert result.exit_code == 0


@pytest.mark.wandb_args(check_output=b"")
def test_local_default(runner, docker, local_settings):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.server, ["start"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        user = getpass.getuser()
        docker.assert_called_with(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "wandb:/vol",
                "-p",
                "8080:8080",
                "--name",
                "wandb-local",
                "-e",
                f"LOCAL_USERNAME={user}",
                "-d",
                "wandb/local",
            ],
            stdout=subprocess.DEVNULL,
        )


@pytest.mark.wandb_args(check_output=b"")
def test_local_custom_port(runner, docker, local_settings):
    result = runner.invoke(cli.server, ["start", "-p", "3030"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    user = getpass.getuser()
    docker.assert_called_with(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "wandb:/vol",
            "-p",
            "3030:8080",
            "--name",
            "wandb-local",
            "-e",
            f"LOCAL_USERNAME={user}",
            "-d",
            "wandb/local",
        ],
        stdout=subprocess.DEVNULL,
    )


@pytest.mark.wandb_args(check_output=b"")
def test_local_custom_env(runner, docker, local_settings):
    result = runner.invoke(cli.server, ["start", "-e", b"FOO=bar"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    user = getpass.getuser()
    docker.assert_called_with(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "wandb:/vol",
            "-p",
            "8080:8080",
            "--name",
            "wandb-local",
            "-e",
            f"LOCAL_USERNAME={user}",
            "-e",
            "FOO=bar",
            "-d",
            "wandb/local",
        ],
        stdout=subprocess.DEVNULL,
    )


@pytest.mark.xfail(
    reason="TODO: fix this test locally; it fails due to a recent docker fixture change"
)
def test_local_already_running(runner, docker, local_settings):
    result = runner.invoke(cli.server, ["start"])
    assert "A container named wandb-local is already running" in result.output


def test_cli_debug_log_scoping(runner, test_settings):
    with runner.isolated_filesystem():
        os.chdir(os.getcwd())
        for test_user in ("user1", "user2"):
            with mock.patch("getpass.getuser", return_value=test_user):
                importlib.reload(cli)
                assert cli._username == test_user
                assert cli._wandb_log_path.endswith(f"debug-cli.{test_user}.log")


@pytest.mark.parametrize(
    "file_age_seconds,age_threshold,should_delete",
    [
        (2 * 24 * 60 * 60, "1d", True),  # 2 day old file, threshold 1 day -> delete
        (1 * 60 * 60, "1d", False),  # 1 hour old file, threshold 1 hour -> keep
    ],
)
def test_purge_cache(
    runner,
    monkeypatch,
    tmp_path,
    file_age_seconds,
    age_threshold,
    should_delete,
):
    cache_dir = tmp_path / "wandb_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(env, "get_cache_dir", lambda: cache_dir)

    # Create a test file with the specified age
    current_time = time.time()
    test_file = cache_dir / "test_file.txt"
    test_file.write_text("test content")
    os.utime(
        test_file,
        (current_time - file_age_seconds, current_time - file_age_seconds),
    )

    result = runner.invoke(cli.purge_cache, ["--age", age_threshold, "--force"])
    assert result.exit_code == 0

    if should_delete:
        assert "Deleted 1 file(s)" in result.output
        assert not test_file.exists(), "File should have been deleted"
    else:
        assert "Deleted 0 file(s)" in result.output
        assert test_file.exists(), "File should still exist"


def test_purge_cache_no_cache_dir(runner, monkeypatch, tmp_path):
    non_existent_dir = tmp_path / "non_existent"
    monkeypatch.setattr(env, "get_cache_dir", lambda: non_existent_dir)

    result = runner.invoke(cli.purge_cache)

    assert result.exit_code == 0
    assert "Cache directory does not exist" in result.output


def test_purge_cache_invalid_age(runner, monkeypatch, tmp_path):
    cache_dir = tmp_path / "wandb_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(env, "get_cache_dir", lambda: cache_dir)

    result = runner.invoke(cli.purge_cache, ["--age", "invalid"])

    assert result.exit_code == 1


def test_purge_cache_subdirectories(runner, monkeypatch, tmp_path):
    cache_dir = tmp_path / "wandb_cache"
    cache_dir.mkdir()
    subdir = cache_dir / "subdir"
    subdir.mkdir()
    monkeypatch.setattr(env, "get_cache_dir", lambda: cache_dir)
    file = subdir / "old_file.txt"
    file.write_text("old content in subdir")
    os.utime(file, (0, 0))

    result = runner.invoke(cli.purge_cache, ["--force"])

    assert result.exit_code == 0
    assert "Deleted 1 file(s)" in result.output
    assert not file.exists()
