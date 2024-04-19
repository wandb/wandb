import pytest
import wandb
from wandb.docker import DockerError
from wandb.sdk.launch.builder.docker_builder import DockerBuilder
from wandb.sdk.launch.utils import docker_image_exists


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


def test_docker_image_exists(monkeypatch):
    def raise_docker_error(args):
        raise DockerError(args, 1, b"", b"")

    monkeypatch.setattr(wandb.docker, "run", lambda args: raise_docker_error(args))
    assert docker_image_exists("test:image") == False
