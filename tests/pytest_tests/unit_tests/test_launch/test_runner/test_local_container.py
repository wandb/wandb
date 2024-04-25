from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.runner.local_container import LocalContainerRunner


@pytest.fixture
def mock_launch_project():
    """Returns a mock LaunchProject object."""
    mock_project = MagicMock()
    mock_project.fill_macros.return_value = {
        "local-container": {"command": "echo hello world"}
    }
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
    mocker.patch("subprocess.Popen", return_value=MagicMock())


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
