import wandb
from wandb.cli import cli
from wandb.apis.internal import InternalApi
import contextlib
import datetime
import traceback
import platform
import getpass
import pytest
import netrc
import subprocess
import sys
import os
from tests import utils

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


def debug_result(result, prefix=None):
    prefix = prefix or ""
    print("DEBUG({}) {} = {}".format(prefix, "out", result.output))
    print("DEBUG({}) {} = {}".format(prefix, "exc", result.exception))
    print(
        "DEBUG({}) {} = {}".format(prefix, "tb", traceback.print_tb(result.exc_info[2]))
    )


def test_init_reinit(runner, empty_netrc, local_netrc, mock_server):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, [DUMMY_API_KEY])
        debug_result(result, "login")
        result = runner.invoke(cli.init, input="y\n\n\n")
        debug_result(result, "init")
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
            result = runner.invoke(cli.login, [DUMMY_API_KEY])
            debug_result(result, "login")
            result = runner.invoke(cli.init, input="y\n%s\nvanpelt\n" % DUMMY_API_KEY)
            debug_result(result, "init")
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


def test_login_host_trailing_slash_fix_invalid(runner, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("machine \n  login user\npassword {}".format(DUMMY_API_KEY))
        result = runner.invoke(
            cli.login, ["--host", "https://google.com/", DUMMY_API_KEY]
        )
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        assert generatedNetrc == (
            "machine google.com\n"
            "  login user\n"
            "  password {}\n".format(DUMMY_API_KEY)
        )


def test_login_bad_host(runner, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, ["--host", "https://app.wandb.ai"])
        assert "did you mean https://api.wandb.ai" in result.output
        assert result.exit_code != 0


def test_login_onprem_key_arg(runner, empty_netrc, local_netrc):
    onprem_key = "test-" + DUMMY_API_KEY
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, [onprem_key])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        assert onprem_key in generatedNetrc


def test_login_invalid_key_arg(runner, empty_netrc, local_netrc):
    invalid_key = "test--" + DUMMY_API_KEY
    with runner.isolated_filesystem():
        result = runner.invoke(cli.login, [invalid_key])
        assert "API key must be 40 characters long, yours was" in str(result)
        assert result.exit_code == 1


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
    # git_repo creates it's own isolated filesystem
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
    # git_repo creates it's own isolated filesystem
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
    # git_repo creates it's own isolated filesystem
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["wandb/test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output


def test_restore_no_entity(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock_server.set_context("git", {"repo": "http://fake.git/foo/bar"})
    monkeypatch.setattr(cli, "_api", InternalApi({"project": "test"}))
    result = runner.invoke(cli.restore, ["test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output


def test_restore_no_diff(runner, mock_server, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
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
    # no patching operaations performed, whether successful or not
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


def test_gc(runner):
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
            == 0
        )
        assert os.path.exists(run1_dir)
        assert not os.path.exists(run2_dir)
        assert (
            runner.invoke(
                cli.sync, ["--clean", "--clean-old-hours", "0"], input="y\n"
            ).exit_code
            == 0
        )
        assert not os.path.exists(run1_dir)


# TODO Investigate unrelated tests failing on Python 3.9
@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="Unrelated tests failing on Python 3.9"
)
@pytest.mark.parametrize("stop_method", ["stop", "cancel"])
def test_sweep_pause(runner, mock_server, test_settings, stop_method):
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


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="Tensorboard not currently built for 3.9"
)
def test_sync_tensorboard(runner, live_mock_server):
    with runner.isolated_filesystem():
        utils.fixture_copy("events.out.tfevents.1585769947.cvp")

        result = runner.invoke(cli.sync, ["."])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Found 1 tfevent files" in result.output
        ctx = live_mock_server.get_ctx()
        print(ctx)
        assert (
            len(utils.first_filestream(ctx)["files"]["wandb-history.jsonl"]["content"])
            == 17
        )

        # Check the no sync tensorboard flag
        result = runner.invoke(cli.sync, [".", "--no-sync-tensorboard"])
        assert result.output == "Skipping directory: {}\n".format(os.path.abspath("."))
        assert os.listdir(".") == ["events.out.tfevents.1585769947.cvp"]


@pytest.mark.flaky
@pytest.mark.xfail(reason="test seems flaky, reenable with WB-5015")
@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="Tensorboard not currently built for 3.9"
)
def test_sync_tensorboard_big(runner, live_mock_server):
    with runner.isolated_filesystem():
        utils.fixture_copy("events.out.tfevents.1611911647.big-histos")
        result = runner.invoke(cli.sync, ["."])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Found 1 tfevent files" in result.output
        assert "exceeds max data limit" in result.output
        ctx = live_mock_server.get_ctx()
        print(ctx)
        assert (
            len(utils.first_filestream(ctx)["files"]["wandb-history.jsonl"]["content"])
            == 27
        )


def test_sync_wandb_run(runner, live_mock_server):
    with runner.isolated_filesystem():
        utils.fixture_copy("wandb")

        result = runner.invoke(cli.sync, ["--sync-all"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        ctx = live_mock_server.get_ctx()
        assert "mock_server_entity/test/runs/g9dvvkua ...done." in result.output
        assert (
            len(utils.first_filestream(ctx)["files"]["wandb-events.jsonl"]["content"])
            == 1
        )

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, ["--sync-all"])
        assert result.exit_code == 0
        assert "wandb: ERROR Nothing to sync." in result.output


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="Tensorboard not currently built for 3.9"
)
def test_sync_wandb_run_and_tensorboard(runner, live_mock_server):
    with runner.isolated_filesystem():
        run_dir = os.path.join("wandb", "offline-run-20210216_154407-g9dvvkua")
        utils.fixture_copy("wandb")
        utils.fixture_copy(
            "events.out.tfevents.1585769947.cvp",
            os.path.join(run_dir, "events.out.tfevents.1585769947.cvp"),
        )

        result = runner.invoke(cli.sync, ["--sync-all"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        ctx = live_mock_server.get_ctx()
        assert "mock_server_entity/test/runs/g9dvvkua ...done." in result.output
        assert (
            len(utils.first_filestream(ctx)["files"]["wandb-events.jsonl"]["content"])
            == 1
        )
        assert ctx["file_bytes"]["code/standalone_tests/code-toad.py"] > 0

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, [run_dir])
        assert result.exit_code == 0
        assert (
            "WARNING Found .wandb file, not streaming tensorboard metrics"
            in result.output
        )
