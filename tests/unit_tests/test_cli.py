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
from wandb.apis.internal import InternalApi
from wandb.cli import cli
from wandb.sdk.lib.apikey import get_netrc_file_path

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


def test_login_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        # reload(wandb)
        result = runner.invoke(cli.login, [dummy_api_key])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open(get_netrc_file_path()) as f:
            generated_netrc = f.read()
        assert dummy_api_key in generated_netrc


def test_login_host_trailing_slash_fix_invalid(runner, dummy_api_key, local_settings):
    with runner.isolated_filesystem():
        with open(get_netrc_file_path(), "w") as f:
            f.write(f"machine \n  login user\npassword {dummy_api_key}")
        result = runner.invoke(
            cli.login, ["--host", "https://google.com/", dummy_api_key]
        )
        assert result.exit_code == 0
        with open(get_netrc_file_path()) as f:
            generated_netrc = f.read()
        assert generated_netrc == (
            f"machine google.com\n  login user\n  password {dummy_api_key}\n"
        )


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


def test_login_onprem_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        onprem_key = "test-" + dummy_api_key
        # with runner.isolated_filesystem():
        result = runner.invoke(cli.login, [onprem_key])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open(get_netrc_file_path()) as f:
            generated_netrc = f.read()
        assert onprem_key in generated_netrc


def test_login_invalid_key_arg(runner, dummy_api_key):
    with runner.isolated_filesystem():
        invalid_key = "test--" + dummy_api_key
        result = runner.invoke(cli.login, [invalid_key])
        assert "API key must be 40 characters long, yours was" in str(result)
        assert result.exit_code == 1


@pytest.mark.skip(reason="Just need to make the mocking work correctly")
def test_login_anonymously(runner, dummy_api_key, monkeypatch, empty_netrc):
    with runner.isolated_filesystem():
        api = InternalApi()
        monkeypatch.setattr(cli, "api", api)
        monkeypatch.setattr(
            wandb.sdk.internal.internal_api.Api,
            "create_anonymous_api_key",
            lambda *args, **kwargs: dummy_api_key,
        )
        result = runner.invoke(cli.login, ["--anonymously"])
        print("Output: ", result.output)
        print("Exception: ", result.exception)
        print("Traceback: ", traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open(get_netrc_file_path()) as f:
            generated_netrc = f.read()
        assert dummy_api_key in generated_netrc


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


def test_cli_login_reprompts_when_no_key_specified(runner, mocker, dummy_api_key):
    with runner.isolated_filesystem():
        mocker.patch("wandb.wandb_lib.apikey.getpass", input)
        # this first gives login an empty API key, which should cause
        # it to re-prompt.  this is what we are testing.  we then give
        # it a valid API key (the dummy API key with a different final
        # letter to check that our monkeypatch input is working as
        # expected) to terminate the prompt finally we grep for the
        # Error: No API key specified to assert that the re-prompt
        # happened
        result = runner.invoke(cli.login, input=f"\n{dummy_api_key[:-1]}q\n")
        with open(get_netrc_file_path()) as f:
            print(f.read())
        assert "ERROR No API key specified." in result.output


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


class TestParseServiceConfig:
    def test_parse_service_config_valid_single(self):
        """Test parsing a single valid service configuration."""
        result = cli.parse_service_config(None, None, ["test_service=always"])
        assert result == {"test_service": "always"}

    def test_parse_service_config_valid_multiple(self):
        """Test parsing multiple valid service configurations."""
        result = cli.parse_service_config(
            None, None, ["service1=always", "service2=never"]
        )
        assert result == {"service1": "always", "service2": "never"}

    def test_parse_service_config_empty(self):
        """Test parsing empty service configurations."""
        result = cli.parse_service_config(None, None, [])
        assert result == {}

    def test_parse_service_config_none(self):
        """Test parsing None service configurations."""
        result = cli.parse_service_config(None, None, None)
        assert result == {}

    def test_parse_service_config_invalid_format_no_equals(self):
        """Test that services without '=' raise an error."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["invalid_service"])
        assert "Service must be in format 'serviceName=policy'" in str(exc_info.value)

    def test_parse_service_config_invalid_format_multiple_equals(self):
        """Test that services with multiple '=' fail due to invalid policy."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["service=policy=extra"])
        assert "Policy must be 'always' or 'never', got 'policy=extra'" in str(
            exc_info.value
        )

    def test_parse_service_config_empty_service_name(self):
        """Test that empty service names raise an error."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["=always"])
        assert "Service name cannot be empty" in str(exc_info.value)

    def test_parse_service_config_whitespace_service_name(self):
        """Test that whitespace-only service names raise an error."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["   =always"])
        assert "Service name cannot be empty" in str(exc_info.value)

    def test_parse_service_config_invalid_policy(self):
        """Test that invalid policies raise an error."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["service=invalid"])
        assert "Policy must be 'always' or 'never', got 'invalid'" in str(
            exc_info.value
        )

    def test_parse_service_config_whitespace_handling(self):
        """Test that whitespace around service names is stripped."""
        result = cli.parse_service_config(None, None, ["  service_name  =always"])
        assert result == {"service_name": "always"}

    def test_service_config_case_sensitivity(self):
        """Test that policy validation is case-sensitive."""
        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["service=Always"])
        assert "Policy must be 'always' or 'never'" in str(exc_info.value)

        with pytest.raises(Exception) as exc_info:
            cli.parse_service_config(None, None, ["service=NEVER"])
        assert "Policy must be 'always' or 'never'" in str(exc_info.value)

    def test_service_config_duplicate_services(self):
        """Test that duplicate service names override previous values."""
        result = cli.parse_service_config(
            None, None, ["service=always", "service=never"]
        )
        assert result == {"service": "never"}  # Last one wins


class TestJobCreateServicesIntegration:
    def test_create_image_job_with_services(self, mocker):
        """Test creating an image job with services that actually generates the wandb-job.json."""
        import json
        from unittest.mock import MagicMock

        from wandb.sdk.artifacts._internal_artifact import InternalArtifact
        from wandb.sdk.launch.create_job import _create_job

        entity = "test-entity"
        proj = "test-services-project"

        # Mock wandb.init to avoid authentication and return a mock run
        mock_run = MagicMock()
        mock_run.id = "test-run-id"
        mocker.patch("wandb.init", return_value=mock_run)

        # Mock API calls
        mock_internal_api = MagicMock()
        mock_internal_api.create_artifact.return_value = ({"state": "PENDING"}, None)

        # Mock the public API and job fetching
        mock_public_api_class = mocker.patch("wandb.Api")
        mock_public_api_instance = MagicMock()
        mock_public_api_class.return_value = mock_public_api_instance

        mock_run_instance = MagicMock()
        mock_public_api_instance.run.return_value = mock_run_instance

        # Capture the JSON content that gets written
        captured_json_content = {}

        def mock_new_file(filename):
            class MockFileContext:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def write(self, content):
                    if filename == "wandb-job.json":
                        captured_json_content[filename] = json.loads(content)

            return MockFileContext()

        # Mock InternalArtifact to capture JSON writes
        mock_artifact = mocker.MagicMock(spec=InternalArtifact)
        mock_artifact._client_id = "mock-client-id"
        mock_artifact._sequence_client_id = "mock-sequence-client-id"
        mock_artifact.new_file.side_effect = mock_new_file
        mock_artifact_class = mocker.patch(
            "wandb.sdk.internal.job_builder.InternalArtifact"
        )
        mock_artifact_class.return_value = mock_artifact

        # Create the job with services
        _create_job(
            api=mock_internal_api,
            path="nicholaspun/train-simple",
            project=proj,
            entity=entity,
            job_type="image",
            description="Test job with services",
            name="test-job-with-services",
            services={"foobar": "always", "barfoo": "never"},
        )

        assert "wandb-job.json" in captured_json_content
        job_json = captured_json_content["wandb-job.json"]
        assert "services" in job_json
        assert job_json["services"] == {"foobar": "always", "barfoo": "never"}

    def test_create_image_job_without_services(self, mocker):
        """Test creating an image job without services - services key should be omitted."""
        import json
        from unittest.mock import MagicMock

        from wandb.sdk.artifacts._internal_artifact import InternalArtifact
        from wandb.sdk.launch.create_job import _create_job

        entity = "test-entity"
        proj = "test-services-project"

        # Mock wandb.init to avoid authentication and return a mock run
        mock_run = MagicMock()
        mock_run.id = "test-run-id"
        mocker.patch("wandb.init", return_value=mock_run)

        # Mock API calls
        mock_internal_api = MagicMock()
        mock_internal_api.create_artifact.return_value = ({"state": "PENDING"}, None)

        # Mock the public API and job fetching
        mock_public_api_class = mocker.patch("wandb.Api")
        mock_public_api_instance = MagicMock()
        mock_public_api_class.return_value = mock_public_api_instance

        mock_run_instance = MagicMock()
        mock_public_api_instance.run.return_value = mock_run_instance

        # Capture the JSON content that gets written
        captured_json_content = {}

        def mock_new_file(filename):
            class MockFileContext:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def write(self, content):
                    if filename == "wandb-job.json":
                        captured_json_content[filename] = json.loads(content)

            return MockFileContext()

        # Mock InternalArtifact to capture JSON writes
        mock_artifact = mocker.MagicMock(spec=InternalArtifact)
        mock_artifact._client_id = "mock-client-id"
        mock_artifact._sequence_client_id = "mock-sequence-client-id"
        mock_artifact.new_file.side_effect = mock_new_file
        mock_artifact_class = mocker.patch(
            "wandb.sdk.internal.job_builder.InternalArtifact"
        )
        mock_artifact_class.return_value = mock_artifact

        # Create the job without services (empty dict)
        _create_job(
            api=mock_internal_api,
            path="nicholaspun/train-simple",
            project=proj,
            entity=entity,
            job_type="image",
            description="Test job without services",
            name="test-job-no-services",
            services={},  # Empty services
        )

        assert "wandb-job.json" in captured_json_content
        job_json = captured_json_content["wandb-job.json"]
        assert "services" not in job_json


class TestJobCreateCLIErrors:
    def test_job_create_invalid_service_format(self, runner, mocker):
        """Test job creation with invalid service format."""
        # Mock minimal dependencies for error testing
        test_entity = "test-entity"
        mocker.patch.dict(
            os.environ, {"WANDB_ENTITY": test_entity, "WANDB_PROJECT": "test-project"}
        )

        with runner.isolated_filesystem():
            result = runner.invoke(
                cli.job,
                [
                    "create",
                    "image",
                    "test:latest",
                    "--name",
                    "test-job",
                    "--service",
                    "invalid_format",
                ],
            )

            assert result.exit_code != 0
            assert "Service must be in format 'serviceName=policy'" in result.output

    def test_job_create_invalid_service_policy(self, runner, mocker):
        """Test job creation with invalid service policy."""
        # Mock minimal dependencies for error testing
        test_entity = "test-entity"
        mocker.patch.dict(
            os.environ, {"WANDB_ENTITY": test_entity, "WANDB_PROJECT": "test-project"}
        )

        with runner.isolated_filesystem():
            result = runner.invoke(
                cli.job,
                [
                    "create",
                    "image",
                    "test:latest",
                    "--name",
                    "test-job",
                    "--service",
                    "service=invalid",
                ],
            )

            assert result.exit_code != 0
            assert "Policy must be 'always' or 'never'" in result.output
