import contextlib
import getpass
import importlib
import netrc
import os
import subprocess
import traceback
from unittest import mock

import pytest
import wandb
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


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet:
        @property
        def hosts(self):
            return {"api.wandb.ai": None}

    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@contextlib.contextmanager
def config_dir():
    try:
        os.environ["WANDB_CONFIG"] = os.getcwd()
        yield
    finally:
        del os.environ["WANDB_CONFIG"]


def debug_result(result, prefix=None):
    prefix = prefix or ""
    print("DEBUG({}) {} = {}".format(prefix, "out", result.output))
    print("DEBUG({}) {} = {}".format(prefix, "exc", result.exception))
    print(
        "DEBUG({}) {} = {}".format(prefix, "tb", traceback.print_tb(result.exc_info[2]))
    )


def test_init_reinit(runner, empty_netrc, user):
    with runner.isolated_filesystem():
        with mock.patch("wandb.sdk.lib.apikey.len", return_value=40):
            result = runner.invoke(cli.login, [user])
        debug_result(result, "login")
        result = runner.invoke(cli.init, input="y\n\n\n")
        debug_result(result, "init")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


def test_init_add_login(runner, empty_netrc, user):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("previous config")
        with mock.patch("wandb.sdk.lib.apikey.len", return_value=40):
            result = runner.invoke(cli.login, [user])
        debug_result(result, "login")
        result = runner.invoke(cli.init, input=f"y\n{user}\nvanpelt\n")
        debug_result(result, "init")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


def test_init_existing_login(runner, user):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write(f"machine localhost\n\tlogin {user}\tpassword {user}")
        result = runner.invoke(cli.init, input="vanpelt\nfoo\n")
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_wandb
        assert "This directory is configured" in result.output


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_pull(runner, wandb_init):
    with runner.isolated_filesystem():
        project_name = "test_pull"
        file_name = "weights.h5"
        run = wandb_init(project=project_name)
        with open(file_name, "w") as f:
            f.write("WEIGHTS")
        run.save(file_name)
        run.finish()

        # delete the file so that we can pull it and check that it is there
        os.remove(file_name)

        result = runner.invoke(cli.pull, [run.id, "--project", project_name])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert f"Downloading: {project_name}/{run.id}" in result.output
        assert os.path.isfile(file_name)
        assert f"File {file_name}" in result.output


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
            "WANDB_DOCKER=%s" % DOCKER_SHA,
            "--runtime",
            "nvidia",
            "%s" % DOCKER_SHA,
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
    monkeypatch.setattr(cli, "find_executable", lambda name: False)
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
        result = runner.invoke(cli.docker, ["test"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
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
    result = runner.invoke(cli.docker, ["test:abc123"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
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
    result = runner.invoke(cli.docker, ["test@sha256:abc123"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
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
    result = runner.invoke(cli.docker, ["test:abc123", "--no-dir"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
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
        cli.docker, ["test:abc123", "--no-tty", "--cmd", "python foo.py"]
    )
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))

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
        result = runner.invoke(cli.docker, ["test", "--jupyter"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))

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
        result = runner.invoke(cli.docker, ["test", "-v", "/tmp:/tmp"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
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
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
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
                "LOCAL_USERNAME=%s" % user,
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
            "LOCAL_USERNAME=%s" % user,
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
            "LOCAL_USERNAME=%s" % user,
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
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert "A container named wandb-local is already running" in result.output


@pytest.mark.parametrize(
    "tb_file_name,history_length",
    [
        ("events.out.tfevents.1585769947.cvp", 17),
        pytest.param(
            "events.out.tfevents.1611911647.big-histos",
            27,
            marks=[
                pytest.mark.flaky,
                pytest.mark.xfail(reason="test seems flaky, reenable with WB-5015"),
            ],
        ),
    ],
)
def test_sync_tensorboard(
    runner,
    relay_server,
    wandb_init,
    copy_asset,
    tb_file_name,
    history_length,
):
    with relay_server() as relay, runner.isolated_filesystem():
        project_name = "test_sync_tensorboard"
        run = wandb.init(project=project_name)
        run.finish()

        copy_asset(tb_file_name)

        result = runner.invoke(
            cli.sync, [".", f"--id={run.id}", f"--project={project_name}"]
        )

        assert result.exit_code == 0
        assert "Found 1 tfevent files" in result.output
        history = relay.context.get_run_history(run.id)
        assert len(history) == history_length

        # Check the no sync tensorboard flag
        result = runner.invoke(cli.sync, [".", "--no-sync-tensorboard"])
        assert "Skipping directory: {}\n".format(os.path.abspath(".")) in result.output
        assert tb_file_name in os.listdir(".")


def test_sync_wandb_run(runner, relay_server, user, copy_asset):
    with relay_server() as relay, runner.isolated_filesystem():
        copy_asset("wandb")

        result = runner.invoke(cli.sync, ["--sync-all"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0

        assert f"{user}/code-toad/runs/g9dvvkua ... done." in result.output
        assert len(relay.context.events) == 1

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, ["--sync-all"])
        assert result.exit_code == 0
        assert "wandb: ERROR Nothing to sync." in result.output


@pytest.mark.xfail(reason="TODO: fix this test")
def test_sync_wandb_run_and_tensorboard(runner, relay_server, user, copy_asset):
    with relay_server() as relay, runner.isolated_filesystem():
        run_dir = os.path.join("wandb", "offline-run-20210216_154407-g9dvvkua")
        copy_asset("wandb")
        tb_file_name = "events.out.tfevents.1585769947.cvp"
        copy_asset(tb_file_name, os.path.join(run_dir, tb_file_name))

        result = runner.invoke(cli.sync, ["--sync-all"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0

        assert f"{user}/code-toad/runs/g9dvvkua ... done." in result.output
        assert len(relay.context.events) == 1

        uploaded_files = relay.context.get_run_uploaded_files("g9dvvkua")
        assert "code/standalone_tests/code-toad.py" in uploaded_files

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, [run_dir])
        assert result.exit_code == 0
        assert (
            "WARNING Found .wandb file, not streaming tensorboard metrics"
            in result.output
        )


def test_cli_debug_log_scoping(runner, test_settings):
    with runner.isolated_filesystem():
        os.chdir(os.getcwd())
        for test_user in ("user1", "user2"):
            with mock.patch("getpass.getuser", return_value=test_user):
                importlib.reload(cli)
                assert cli._username == test_user
                assert cli._wandb_log_path.endswith(f"debug-cli.{test_user}.log")
