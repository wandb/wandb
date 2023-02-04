from unittest.mock import MagicMock

from wandb.sdk.launch.registry.elastic_container_registry import (
    ElasticContainerRegistry,
)


def test_ecr_verify():
    """Test that the ECR registry is verified correctly."""
    client = MagicMock()
    client.describe_registry.return_value = {"registryId": "123456789012"}
    client.describe_repositories.return_value = {
        "repositories": [
            {"repositoryUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"}
        ]
    }
    session = MagicMock()
    session.client.return_value = client
    environment = MagicMock()
    environment.get_session.return_value = session
    ecr = ElasticContainerRegistry("my-repo", environment)
    ecr.verify()
    assert ecr.uri == "123456789012.dkr.ecr.us-east-1.amazonaws.com"


def test_ecr_get_username_password():
    """Test that the ECR registry returns the correct username and password."""
    client = MagicMock()
    client.get_authorization_token.return_value = {
        "authorizationData": [
            {
                "authorizationToken": "dXNlcjpwYXNzd29yZA==",
            }
        ]
    }
    session = MagicMock()
    session.client.return_value = client
    environment = MagicMock()
    environment.get_session.return_value = session
    ecr = ElasticContainerRegistry("my-repo", environment)
    username, password = ecr.get_username_password()
    assert username == "user"
    assert password == "password"


def test_check_image_exists(mocker):
    """Test that the ECR registry checks if an image exists correctly."""
    client = MagicMock()
    client.describe_images.return_value = {
        "imageDetails": [
            {
                "imageDigest": "sha256:1234567890123456789012345678901234567890123456789012345678901234",
                "imageTags": ["latest"],
            }
        ]
    }
    session = MagicMock()
    session.client.return_value = client
    environment = MagicMock()
    environment.get_session.return_value = session
    ecr = ElasticContainerRegistry("my-repo", environment)
    ecr.uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    mocker.patch(
        "wandb.sdk.launch.registry.elastic_container_registry.ElasticContainerRegistry.get_username_password",
        return_value=("user", "password"),
    )
    assert ecr.check_image_exists("blahblahblah:latest")
    client.describe_images.assert_called_once_with(
        repositoryName="my-repo",
        imageIds=[
            {
                "imageTag": "latest",
            }
        ],
        filter={"tagStatus": "TAGGED"},
    )

    # Assert we return false for an image that doesn't exist.
    assert not ecr.check_image_exists("blahblahblah:faketag")
