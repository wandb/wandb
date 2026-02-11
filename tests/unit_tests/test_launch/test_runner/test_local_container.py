import os
import platform
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner import local_container
from wandb.sdk.launch.runner.local_container import LocalContainerRunner


@pytest.fixture
def mock_launch_project(tmpdir):
    """Returns a mock LaunchProject object."""
    mock_project = MagicMock()
    mock_project.fill_macros.return_value = {
        "local-container": {"command": "echo hello world"}
    }
    mock_project.get_job_entry_point.return_value = MagicMock(command=["echo", "hello"])
    mock_project.project_dir = tmpdir
    mock_project.override_args = None
    yield mock_project


@pytest.fixture
def mock_pull_docker_image(mocker):
    """Patches the docker image pull method with a dummy."""
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.pull_docker_image", return_value=None
    )


@pytest.fixture
def mock_popen(mocker):
    """Patches the subprocess.Popen method with a dummy."""
    _mock_popen = MagicMock()
    mocker.patch("subprocess.Popen", _mock_popen)
    return _mock_popen


@pytest.mark.asyncio
async def test_local_container_runner(
    mock_launch_project, test_settings, mock_pull_docker_image, test_api, mock_popen
):
    runner = LocalContainerRunner(
        test_api, {"SYNCHRONOUS": True}, MagicMock(), MagicMock()
    )
    image_uri = "test-image-uri"
    mock_launch_project.docker_image = image_uri
    await runner.run(mock_launch_project, image_uri)


@pytest.mark.asyncio
async def test_local_container_base_image_job(
    mock_launch_project, test_settings, mock_pull_docker_image, test_api, mock_popen
):
    """Test that we modify the docker run command to mount source code into base image.

    This should happen when the launch project has the job_base_image attribute set.
    """
    runner = LocalContainerRunner(
        test_api, {"SYNCHRONOUS": True}, MagicMock(), MagicMock()
    )
    image_uri = "test-image-uri"
    mock_launch_project.job_base_image = image_uri

    await runner.run(mock_launch_project, image_uri)
    command = mock_popen.call_args[0][0]
    if os.name == "nt":
        assert command[:2] == ["cmd", "/C"]
    else:
        assert command[1] == "-c"
        assert os.path.basename(command[0]) in ("bash", "sh")
    docker_command = command[2].split(" ")
    assert docker_command[:7] == [
        "docker",
        "run",
        "--rm",
        "--command",
        "'echo",
        "hello",
        "world'",
    ]
    mount_string = f"{mock_launch_project.project_dir}:/mnt/wandb"
    if platform.system() == "Windows":
        mount_string = f"'{mount_string}'"
    assert docker_command[7:9] == ["--volume", mount_string]
    assert docker_command[9:11] == ["--workdir", "/mnt/wandb"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell selection test")
def test_shell_command_prefers_bash(mocker):
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.shutil.which",
        side_effect=lambda cmd: "/usr/bin/bash" if cmd == "bash" else None,
    )

    assert local_container._shell_command("echo hello") == [
        "/usr/bin/bash",
        "-c",
        "echo hello",
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell selection test")
def test_shell_command_falls_back_to_sh(mocker):
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.shutil.which",
        side_effect=lambda cmd: "/bin/sh" if cmd == "sh" else None,
    )

    assert local_container._shell_command("echo hello") == [
        "/bin/sh",
        "-c",
        "echo hello",
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell selection test")
def test_shell_command_raises_when_no_shell(mocker):
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.shutil.which",
        return_value=None,
    )

    with pytest.raises(LaunchError, match="no compatible shell found"):
        local_container._shell_command("echo hello")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX shell selection test")
async def test_local_container_runner_uses_sh_when_bash_missing(
    mock_launch_project,
    test_settings,
    mock_pull_docker_image,
    test_api,
    mock_popen,
    mocker,
):
    """Verify runner interface works when bash is unavailable."""
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.shutil.which",
        side_effect=lambda cmd: "/bin/sh" if cmd == "sh" else None,
    )
    runner = LocalContainerRunner(
        test_api, {"SYNCHRONOUS": True}, MagicMock(), MagicMock()
    )
    image_uri = "test-image-uri"
    mock_launch_project.docker_image = image_uri

    await runner.run(mock_launch_project, image_uri)

    command = mock_popen.call_args[0][0]
    assert len(command) == 3, "Expected [shell, '-c', command]"
    assert os.path.basename(command[0]) == "sh"
    assert command[1] == "-c"
    assert "echo hello world" in command[2]


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX shell selection test")
async def test_local_container_runner_raises_when_no_compatible_shell(
    mock_launch_project,
    test_settings,
    mock_pull_docker_image,
    test_api,
    mock_popen,
    mocker,
):
    """Verify runner interface provides a clear error without bash/sh."""
    mocker.patch(
        "wandb.sdk.launch.runner.local_container.shutil.which",
        return_value=None,
    )
    runner = LocalContainerRunner(
        test_api, {"SYNCHRONOUS": True}, MagicMock(), MagicMock()
    )
    image_uri = "test-image-uri"
    mock_launch_project.docker_image = image_uri

    with pytest.raises(LaunchError, match="no compatible shell found"):
        await runner.run(mock_launch_project, image_uri)
