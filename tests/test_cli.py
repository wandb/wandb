import wandb
from wandb.cli import cli
from wandb.apis.internal import InternalApi
import contextlib
import traceback
import platform
import getpass
import pytest
import netrc
import subprocess
import os

DUMMY_API_KEY = "1824812581259009ca9981580f8f8a9012409eee"
DOCKER_SHA = (
    "wandb/deepo@sha256:"
    "3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177"
)


@pytest.fixture
def docker(request, mock_server, mocker, monkeypatch):
    wandb_args = {"check_output": b"wandb/deepo@sha256:abc123"}
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
def no_tty(mocker):
    with mocker.patch("wandb.sys.stdin") as stdin_mock:
        stdin_mock.isatty.return_value = False
        yield


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet(object):
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


def test_init_reinit(runner, empty_netrc, local_netrc, mock_server):
    with runner.isolated_filesystem():
        runner.invoke(cli.login, [DUMMY_API_KEY])
        result = runner.invoke(cli.init, input="y\n\n\n")
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "mock_server_entity" in generatedWandb


def test_init_add_login(runner, empty_netrc, mock_server):
    with runner.isolated_filesystem():
        with config_dir():
            with open("netrc", "w") as f:
                f.write("previous config")
            runner.invoke(cli.login, [DUMMY_API_KEY])
            result = runner.invoke(cli.init, input="y\n%s\nvanpelt\n" % DUMMY_API_KEY)
            print(result.output)
            print(result.exception)
            print(traceback.print_tb(result.exc_info[2]))
            assert result.exit_code == 0
            with open("netrc", "r") as f:
                generatedNetrc = f.read()
            with open("wandb/settings", "r") as f:
                generatedWandb = f.read()
            assert DUMMY_API_KEY in generatedNetrc
            assert "base_url" in generatedWandb


def test_init_existing_login(runner, mock_server):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("machine api.wandb.ai\n\tlogin test\tpassword 12345")
        result = runner.invoke(cli.init, input="vanpelt\nfoo\n")
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert "mock_server_entity" in generatedWandb
        assert "This directory is configured" in result.output


@pytest.mark.skip(reason="Currently dont have on in cling")
def test_enable_on(runner, git_repo):
    with open("wandb/settings", "w") as f:
        f.write("[default]\nproject=rad")
    result = runner.invoke(cli.on)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "W&B enabled" in str(result.output)
    assert result.exit_code == 0


@pytest.mark.skip(reason="Currently dont have off in cling")
def test_enable_off(runner, git_repo):
    with open("wandb/settings", "w") as f:
        f.write("[default]\nproject=rad")
    result = runner.invoke(cli.off)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "W&B disabled" in str(result.output)
    assert "disabled" in open("wandb/settings").read()
    assert result.exit_code == 0


def test_pull(runner, mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.pull, ["test", "--project", "test"])

        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Downloading: test/test" in result.output
        assert os.path.isfile("weights.h5")
        assert "File weights.h5" in result.output


def test_no_project_bad_command(runner):
    result = runner.invoke(cli.cli, ["fsd"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "No such command" in result.output
    assert result.exit_code == 2


def test_login_key_arg(runner, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        # reload(wandb)
        result = runner.invoke(cli.login, [DUMMY_API_KEY])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        assert DUMMY_API_KEY in generatedNetrc


@pytest.mark.skip(reason="Just need to make the mocking work correctly")
def test_login_anonymously(runner, monkeypatch, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        api = InternalApi()
        monkeypatch.setattr(cli, "api", api)
        monkeypatch.setattr(
            api, "create_anonymous_api_key", lambda *args, **kwargs: DUMMY_API_KEY
        )
        result = runner.invoke(cli.login, ["--anonymously"])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generated_netrc = f.read()
        assert DUMMY_API_KEY in generated_netrc


def test_artifact_download(runner, git_repo, mock_server):
    result = runner.invoke(cli.artifact, ["get", "test/mnist:v0"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Downloading dataset artifact" in result.output
    path = os.path.join(".", "artifacts", "mnist:v0")
    if platform.system() == "Windows":
        path = path.replace(":", "-")
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
    assert "9KB" in result.output
    assert "mnist:v2" in result.output


def test_docker_run_digest(runner, docker, monkeypatch):
    result = runner.invoke(cli.docker_run, [DOCKER_SHA],)
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
    result = runner.invoke(cli.local)
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
    result = runner.invoke(cli.local, ["-p", "3030"])
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
    result = runner.invoke(cli.local, ["-e", b"FOO=bar"])
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


def test_local_already_running(runner, docker, local_settings):
    result = runner.invoke(cli.local)
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert "A container named wandb-local is already running" in result.output