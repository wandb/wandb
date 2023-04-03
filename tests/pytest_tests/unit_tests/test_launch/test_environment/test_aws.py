import os
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.utils import LaunchError


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


def test_verify_storage(mocker):
    """Test that the AwsEnvironment correctly verifies storage."""
    session = MagicMock()
    client = MagicMock()
    client.head_bucket.return_value = "Success!"
    session.client.return_value = client
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        return_value=session,
    )
    environment = _get_environment()
    environment.verify_storage_uri("s3://bucket/key")

    def _raise(*args, **kwargs):
        raise ClientError({}, "Error")

    environment.get_session = _raise
    with pytest.raises(LaunchError):
        environment.verify_storage_uri("s3://bucket/key")


def test_verify(mocker):
    """Test that the AwsEnvironment correctly verifies."""
    session = MagicMock()
    client = MagicMock()
    client.get_caller_identity.return_value = "Success!"
    session.client.return_value = client
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        return_value=session,
    )
    environment = _get_environment()
    environment.verify()


def test_upload_directory(mocker):
    """Test that we issue the correct api calls to upload files to s3."""
    """
    Step one here is to mock the os.walk function to return a list of files
    corresponding to the following directory structure:
    source_dir
    ├── Dockerfile
    ├── main.py
    ├── module
    │   ├── submodule
    │   │   ├── that.py
    │   │   └── this.py
    │   ├── dataset.py
    │   ├── eval.py
    │   └── model.py
    └── requirements.txt
    """
    source_dir = "source_dir"
    walk_output = [
        (f"{source_dir}", None, ["Dockerfile", "main.py", "requirements.txt"]),
        (os.path.join(source_dir, "module"), "", ["dataset.py", "eval.py", "model.py"]),
        (
            os.path.join(source_dir, "module", "submodule"),
            "",
            [
                "that.py",
                "this.py",
            ],
        ),
    ]
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.walk",
        return_value=walk_output,
    )
    session = MagicMock()
    client = MagicMock()

    session.client.return_value = client
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        return_value=session,
    )
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isdir", return_value=True
    )

    environment = AwsEnvironment(
        region="us-west-2",
        access_key="access_key",
        secret_key="secret_key",
        session_token="token",
        verify=False,
    )
    environment.upload_dir(source_dir, "s3://bucket/key")
    assert client.upload_file.call_count == 8
    assert client.upload_file.has_calls(
        [
            mocker.call(
                os.path.join(source_dir, "Dockerfile"),
                f"{source_dir}/Dockerfile",
                "bucket",
                "key/Dockerfile",
            ),
            mocker.call(
                os.path.join(source_dir, "main.py"),
                "bucket",
                "key/main.py",
            ),
            mocker.call(
                os.path.join(source_dir, "requirements.txt"),
                "bucket",
                "key/requirements.txt",
            ),
            mocker.call(
                os.path.join(source_dir, "module", "dataset.py"),
                "bucket",
                "key/module/dataset.py",
            ),
            mocker.call(
                os.path.join(source_dir, "module", "eval.py"),
                "bucket",
                "key/module/eval.py",
            ),
            mocker.call(
                os.path.join(source_dir, "module", "model.py"),
                "bucket",
                "key/module/model.py",
            ),
            mocker.call(
                os.path.join(source_dir, "module", "submodule", "that.py"),
                "bucket",
                "key/module/submodule/that.py",
            ),
            mocker.call(
                os.path.join(source_dir, "module", "submodule", "this.py"),
                "bucket",
                "key/module/submodule/this.py",
            ),
        ]
    )


def test_upload_invalid_path(mocker):
    """Test that we raise an error for invalid paths.

    The upload can't proceed if
    - the source path is not a directory, or
    - the destination path is not a valid S3 URI
    """
    environment = _get_environment()
    with pytest.raises(LaunchError) as e:
        environment.upload_dir("invalid_path", "s3://bucket/key")
    assert "Source invalid_path does not exist." == str(e.value)
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isdir",
        return_value=True,
    )
    for path in ["s3a://bucket/key", "s3n://bucket/key"]:
        with pytest.raises(LaunchError) as e:
            environment.upload_dir("tests", path)
        assert f"Destination {path} is not a valid s3 URI." == str(e.value)


def test_upload_file(mocker):
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        return_value=session,
    )
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isfile", return_value=True
    )
    environment = _get_environment()
    environment.upload_file("source_file", "s3://bucket/key")
    assert client.upload_file.call_args_list[0][0] == (
        "source_file",
        "bucket",
        "key",
    )
    with pytest.raises(LaunchError) as e:
        environment.upload_file("source_file", "s3a://bucket/key")
        assert e.content == "Destination s3a://bucket/key is not a valid s3 URI."
