from unittest.mock import MagicMock

import botocore.exceptions
import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.registry.elastic_container_registry import (
    ElasticContainerRegistry,
)


@pytest.mark.parametrize(
    "uri, account_id, region, repo_name, expected_uri",
    [
        # Case we have the uri.
        (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo",
            None,
            None,
            None,
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo",
        ),
        # Case we have the account_id, region, and repo_name.
        (
            None,
            "123456789012",
            "us-east-1",
            "my-repo",
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo",
        ),
        # Case we have nothing, fails.
        (None, None, None, None, None),
        # Case we have some of the optional fields.
        (
            None,
            "123456789012",
            None,
            "my-repo",
            None,
        ),
        # Another case like that.
        (
            None,
            None,
            "us-east-1",
            "my-repo",
            None,
        ),
    ],
)
def test_ecr_init(uri, account_id, region, repo_name, expected_uri):
    """This tests how we initialize the ElasticContainerRegistry.

    It basically just checks that we always set the arguments correctly.
    """
    if expected_uri is None:
        with pytest.raises(LaunchError):
            ecr = ElasticContainerRegistry(uri, account_id, region, repo_name)
    else:
        ecr = ElasticContainerRegistry(uri, account_id, region, repo_name)
        assert ecr.uri == expected_uri
        assert ecr.account_id == "123456789012"
        assert ecr.region == "us-east-1"
        assert ecr.repo_name == "my-repo"


@pytest.fixture
def mock_boto3_session(monkeypatch):
    """This fixture mocks boto3.Session and returns that object."""
    mock_session = MagicMock()
    monkeypatch.setattr(
        "boto3.Session",
        lambda *args, **kwargs: mock_session,
    )
    return mock_session


@pytest.fixture
def mock_ecr_client(mock_boto3_session):
    """This fixture mocks boto3.Session.client and returns that object."""
    mock_ecr_client = MagicMock()
    mock_boto3_session.client.return_value = mock_ecr_client
    return mock_ecr_client


@pytest.mark.asyncio
async def test_check_image_exists_success(mock_ecr_client):
    """This tests that we check if the image exists.

    It basically just checks that we call boto3 correctly.
    """
    # First we test that we return True if we get a response.
    mock_ecr_client.describe_images.return_value = {
        "imageDetails": [
            {
                "imageDigest": "sha256:1234567890",
                "imageTags": ["my-image"],
            }
        ]
    }
    ecr = ElasticContainerRegistry(
        uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )
    assert await ecr.check_image_exists(
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo:my-image"
    )
    assert mock_ecr_client.describe_images.call_args[1] == {
        "repositoryName": "my-repo",
        "imageIds": [{"imageTag": "my-image"}],
    }


@pytest.mark.asyncio
async def test_check_image_exists_doesnt_exist(mock_ecr_client):
    """Check that we return False if the image doesn't exist."""
    ecr = ElasticContainerRegistry(
        uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )
    mock_ecr_client.describe_images.side_effect = botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "ImageNotFoundException",
                "Message": "We could not find it!",
            }
        },
        "DescribeImages",
    )
    assert not await ecr.check_image_exists("my-image")


@pytest.mark.asyncio
async def test_check_image_exists_other_error(mock_ecr_client):
    """This tests that we raise a LaunchError if we get receive an error response."""
    ecr = ElasticContainerRegistry(
        uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )
    mock_ecr_client.describe_images.side_effect = botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "SomeOtherError",
                "Message": "We could not find it!",
            }
        },
        "DescribeImages",
    )
    with pytest.raises(LaunchError):
        await ecr.check_image_exists("my-image")


@pytest.mark.asyncio
async def test_get_username_password_success(mock_ecr_client):
    """This tests that we get the username and password.

    It basically just checks that we call boto3 correctly.
    """
    mock_ecr_client.get_authorization_token.return_value = {
        "authorizationData": [
            {
                "authorizationToken": "dXNlcm5hbWU6cGFzc3dvcmQ=",
                "expiresAt": "2021-08-25T20:30:00Z",
                "proxyEndpoint": "https://123456789012.dkr.ecr.us-east-1.amazonaws.com",
            }
        ]
    }
    ecr = ElasticContainerRegistry(
        uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )
    assert await ecr.get_username_password() == ("username", "password")


@pytest.mark.asyncio
async def test_get_username_password_fails(mock_ecr_client):
    """This tests that we raise a LaunchError if we get receive an error response."""
    ecr = ElasticContainerRegistry(
        uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo"
    )
    mock_ecr_client.get_authorization_token.side_effect = (
        botocore.exceptions.ClientError(
            {
                "Error": {
                    "Code": "SomeOtherError",
                    "Message": "We could not find it!",
                }
            },
            "GetAuthorizationToken",
        )
    )
    with pytest.raises(LaunchError):
        await ecr.get_username_password()
