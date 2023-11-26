import pytest
from wandb.sdk.launch.builder.docker_builder import DockerBuilder


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
