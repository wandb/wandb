import datetime
import getpass
import importlib
import netrc
import os
import subprocess
import traceback
from unittest import mock

import pytest
import wandb
import wandb.docker
from wandb.cli import cli

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
    api_key = mocker.patch(
        "wandb.apis.InternalApi.api_key", new_callable=mocker.PropertyMock
    )
    api_key.return_value = "test"
    monkeypatch.setattr(cli, "_HAS_NVIDIA_DOCKER", True)
    monkeypatch.setattr(cli, "_HAS_DOCKER", True)
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


@pytest.mark.usefixtures("patch_apikey")
def test_sync_gc(runner):
    with runner.isolated_filesystem():
        if not os.path.isdir("wandb"):
            os.mkdir("wandb")
        d1 = datetime.datetime.now()
        d2 = d1 - datetime.timedelta(hours=3)
        run1 = d1.strftime("run-%Y%m%d_%H%M%S-abcd")
        run2 = d2.strftime("run-%Y%m%d_%H%M%S-efgh")
        run1_dir = os.path.join("wandb", run1)
        run2_dir = os.path.join("wandb", run2)
        os.mkdir(run1_dir)
        with open(os.path.join(run1_dir, "run-abcd.wandb"), "w") as f:
            f.write("")
        with open(os.path.join(run1_dir, "run-abcd.wandb.synced"), "w") as f:
            f.write("")
        os.mkdir(run2_dir)
        with open(os.path.join(run2_dir, "run-efgh.wandb"), "w") as f:
            f.write("")
        with open(os.path.join(run2_dir, "run-efgh.wandb.synced"), "w") as f:
            f.write("")
        assert (
            runner.invoke(
                cli.sync, ["--clean", "--clean-old-hours", "2"], input="y\n"
            ).exit_code
        ) == 0

        assert os.path.exists(run1_dir)
        assert not os.path.exists(run2_dir)
        assert (
            runner.invoke(
                cli.sync, ["--clean", "--clean-old-hours", "0"], input="y\n"
            ).exit_code
            == 0
        )
        assert not os.path.exists(run1_dir)


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
            "WANDB_API_KEY=test",
            "-e",
            f"WANDB_DOCKER={DOCKER_SHA}",
            "--runtime",
            "nvidia",
            f"{DOCKER_SHA}",
        ]
    )


def test_docker_run_bad_image(runner, docker, monkeypatch):
    result = runner.invoke(cli.docker_run, ["wandb///foo$"])
    assert result.exit_code == 0
    docker.assert_called_once_with(
        [
            "docker",
            "run",
            "-e",
            "WANDB_API_KEY=test",
            "--runtime",
            "nvidia",
            "wandb///foo$",
        ]
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
            "WANDB_API_KEY=test",
            "-e",
            "WANDB_DOCKER=wandb/deepo@sha256:abc123",
            "-v",
            "cool:/cool",
            "rad",
        ]
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
            "WANDB_API_KEY=test",
            "-e",
            "WANDB_DOCKER=wandb/deepo@sha256:abc123",
            "--runtime",
            "nvidia",
            "-v",
            "cool:/cool",
            "rad",
            "/bin/bash",
            "cool",
        ]
    )


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
                "WANDB_API_KEY=test",
                "-it",
                "test",
                "/bin/bash",
            ]
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
            "WANDB_API_KEY=test",
            "-it",
            "test:abc123",
            "/bin/bash",
        ]
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
            "WANDB_API_KEY=test",
            "-it",
            "test@sha256:abc123",
            "/bin/bash",
        ]
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
            "WANDB_API_KEY=test",
            "-it",
            "test:abc123",
            "/bin/bash",
        ]
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
            "WANDB_API_KEY=test",
            "test:abc123",
            "/bin/bash",
            "-c",
            "python foo.py",
        ]
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
                "WANDB_API_KEY=test",
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
            ]
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
                "WANDB_API_KEY=test",
                "test",
                "-v",
                "/tmp:/tmp",
                "-it",
                "wandb/deepo:all-cpu",
                "/bin/bash",
            ]
        )
        assert result.exit_code == 0


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
            ]
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
        ]
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
        ]
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
