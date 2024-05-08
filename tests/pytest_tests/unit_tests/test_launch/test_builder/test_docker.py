import platform
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch._project_spec import EntryPoint
from wandb.sdk.launch.builder.docker_builder import DockerBuilder
from wandb.sdk.launch.registry.local_registry import LocalRegistry


@pytest.fixture
def mock_ecr_registry(monkeypatch):
    monkeypatch.setattr(
        "wandb.sdk.launch.builder.docker_builder.registry_from_uri",
        lambda uri: uri,
    )


def test_docker_builder_with_uri(mock_ecr_registry):
    docker_builder = DockerBuilder.from_config(
        {
            "type": "docker",
            "destination": "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo",
        },
        None,
        None,
    )
    assert (
        docker_builder.registry
        == "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )


@pytest.fixture
def mock_validate_docker_installation(mocker):
    """Mock the validate_docker_installation function for testing."""
    mocker.patch(
        "wandb.sdk.launch.builder.docker_builder.validate_docker_installation",
        return_value=True,
    )


@pytest.fixture
def mock_build_context_manager(mocker):
    """Mock the build context manager for testing.

    This sets the return value of the BuildContextManager to a MagicMock object
    and returns the object for manipulation in the test.
    """
    mock_context_manager = MagicMock()
    mock_context_manager.create_build_context = MagicMock(
        return_value=(
            "path",
            "image_tag",
        )
    )
    mocker.patch(
        "wandb.sdk.launch.builder.docker_builder.BuildContextManager",
        return_value=mock_context_manager,
    )
    return mock_context_manager


@pytest.fixture
def mock_launch_project():
    """Mock the launch project for testing."""
    project = MagicMock()
    project.image_name = "test_image"
    project.override_entrypoint = EntryPoint("train.py", ["python", "train.py"])
    project.override_args = ["--epochs", "10"]
    project.project_dir = "/tmp/project_dir"
    project.get_env_vars_dict = MagicMock(
        return_value={
            "WANDB_API_KEY": "test_api_key",
            "WANDB_PROJECT": "test_project",
            "WANDB_ENTITY": "test_entity",
        }
    )
    return project


@pytest.fixture
def mock_docker_build(mocker):
    """Mock the docker build command for testing."""
    mock_build = MagicMock(return_value="build logs")
    mocker.patch("wandb.sdk.launch.builder.docker_builder.docker.build", mock_build)
    return mock_build


@pytest.mark.asyncio
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows handles the path differently and isn't supported",
)
async def test_docker_builder_build(
    mock_launch_project,
    mock_build_context_manager,
    mock_docker_build,
    mock_validate_docker_installation,
):
    """Tests that the docker builder build_image function works correctly.

    The builder should use a BuildContextManager to create the build context
    for the build and then call a docker build command with the correct arguments.
    We mock the docker module and BuildContextManager to check that the call was
    made with the correct arguments.
    """
    docker_builder = DockerBuilder.from_config(
        {
            "type": "docker",
        },
        None,
        LocalRegistry(),
    )
    await docker_builder.build_image(
        mock_launch_project,
        mock_launch_project.override_entrypoint,
        MagicMock(),
    )

    mock_docker_build.assert_called_once_with(
        tags=["test_image:image_tag"],
        file="path/Dockerfile.wandb",
        context_path="path",
        platform=None,
    )
