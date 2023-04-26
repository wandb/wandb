from unittest.mock import MagicMock

from wandb.sdk.launch.environment.aws_environment import AwsEnvironment


def _get_environment():
    return AwsEnvironment(
        region="us-west-2",
        secret_key="secret_key",
        access_key="access_key",
        session_token="token",
        verify=False,
    )


def test_from_default(mocker) -> None:
    """Test creating an AWS environment from the default credentials."""
    boto3 = MagicMock()
    session = MagicMock()
    credentials = MagicMock()
    credentials.access_key = "access_key"
    credentials.secret_key = "secret_key"
    credentials.token = "token"
    session.get_credentials.return_value = credentials
    boto3.Session.return_value = session
    mocker.patch("wandb.sdk.launch.environment.aws_environment.boto3", boto3)
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment", MagicMock()
    )
    default_environment = AwsEnvironment.from_default(region="us-west-2", verify=False)
    assert default_environment._region == "us-west-2"
    assert default_environment._access_key == "access_key"
    assert default_environment._secret_key == "secret_key"
    assert default_environment._session_token == "token"
