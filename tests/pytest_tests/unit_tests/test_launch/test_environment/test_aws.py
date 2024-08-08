import os
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.errors import LaunchError


def _get_environment():
    return AwsEnvironment(
        region="us-west-2",
        secret_key="secret_key",
        access_key="access_key",
        session_token="token",
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
    default_environment = AwsEnvironment.from_default(region="us-west-2")
    assert default_environment._region == "us-west-2"
    assert default_environment._access_key == "access_key"
    assert default_environment._secret_key == "secret_key"
    assert default_environment._session_token == "token"


@pytest.mark.asyncio
async def test_verify_storage(mocker):
    """Test that the AwsEnvironment correctly verifies storage."""
    session = MagicMock()
    client = MagicMock()
    session.client.return_value = client
    client.head_bucket.return_value = "Success!"

    async def _mock_get_session(*args, **kwargs):
        return session

    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        _mock_get_session,
    )
    environment = _get_environment()
    await environment.verify_storage_uri("s3://bucket/key")

    for code in [404, 403, 0]:
        client.head_bucket.side_effect = ClientError({"Error": {"Code": code}}, "Error")
        with pytest.raises(LaunchError):
            await environment.verify_storage_uri("s3://bucket/key")

    with pytest.raises(LaunchError):
        await environment.verify_storage_uri("s3a://bucket/key")


@pytest.mark.asyncio
async def test_verify(mocker):
    """Test that the AwsEnvironment correctly verifies."""
    session = MagicMock()
    client = MagicMock()
    identity = MagicMock()
    identity.get.return_value = "123456789012"
    client.get_caller_identity.return_value = identity

    async def _mock_get_session(*args, **kwargs):
        return session

    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        _mock_get_session,
    )
    environment = _get_environment()
    await environment.verify()


@pytest.mark.asyncio
@pytest.mark.xfail(reason="`assert_has_calls` vs `assert <...>.has_calls`")
async def test_upload_directory(mocker):
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

    async def _mock_get_session(*args, **kwargs):
        return session

    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        _mock_get_session,
    )
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isdir", return_value=True
    )

    environment = AwsEnvironment(
        region="us-west-2",
        access_key="access_key",
        secret_key="secret_key",
        session_token="token",
    )
    await environment.upload_dir(source_dir, "s3://bucket/key")
    assert client.upload_file.call_count == 8
    client.upload_file.assert_has_calls(
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


@pytest.mark.asyncio
async def test_upload_invalid_path(mocker):
    """Test that we raise an error for invalid paths.

    The upload can't proceed if
    - the source path is not a directory, or
    - the destination path is not a valid S3 URI
    """
    environment = _get_environment()
    with pytest.raises(LaunchError) as e:
        await environment.upload_dir("invalid_path", "s3://bucket/key")
    assert "Source invalid_path does not exist." in str(e.value)
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isdir",
        return_value=True,
    )
    for path in ["s3a://bucket/key", "s3n://bucket/key"]:
        with pytest.raises(LaunchError) as e:
            await environment.upload_dir("tests", path)
        assert f"Destination {path} is not a valid s3 URI." in str(e.value)


@pytest.mark.asyncio
async def test_upload_file(mocker):
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client

    async def _mock_get_session(*args, **kwargs):
        return session

    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        _mock_get_session,
    )
    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.os.path.isfile", return_value=True
    )
    environment = _get_environment()
    await environment.upload_file("source_file", "s3://bucket/key")
    assert client.upload_file.call_args_list[0][0] == (
        "source_file",
        "bucket",
        "key",
    )
    with pytest.raises(LaunchError) as e:
        await environment.upload_file("source_file", "s3a://bucket/key")
        assert e.content == "Destination s3a://bucket/key is not a valid s3 URI."


@pytest.mark.parametrize(
    "arn, partition, raises",
    [
        ("arn:aws:iam::123456789012:user/JohnDoe", "aws", False),
        ("arn:aws-cn:iam::123456789012:user/JohnDoe", "aws-cn", False),
        ("arn:aws-us-gov:iam::123456789012:user/JohnDoe", "aws-us-gov", False),
        ("arn:aws-iso:iam::123456789012:user/JohnDoe", "aws-iso", False),
        ("arn:aws:imail:123456789012:user/JohnDoe", None, True),
    ],
)
@pytest.mark.asyncio
async def test_get_partition(mocker, arn, partition, raises):
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    client.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": arn,
    }

    async def _mock_get_session(*args, **kwargs):
        return session

    mocker.patch(
        "wandb.sdk.launch.environment.aws_environment.AwsEnvironment.get_session",
        _mock_get_session,
    )
    environment = _get_environment()
    if not raises:
        part = await environment.get_partition()
        assert part == partition
    else:
        with pytest.raises(LaunchError) as e:
            await environment.get_partition()
        assert (
            f"Could not set partition for AWS environment. ARN {arn} is not valid."
            in str(e.value)
        )
