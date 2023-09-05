"""Implements the AWS environment."""

import logging
import os
import re
from typing import Dict

from wandb.sdk.launch.errors import LaunchError
from wandb.util import get_module

from .abstract import AbstractEnvironment

boto3 = get_module(
    "boto3",
    required="AWS environment requires boto3 to be installed. Please install "
    "it with `pip install wandb[launch]`.",
)
botocore = get_module(
    "botocore",
    required="AWS environment requires botocore to be installed. Please install "
    "it with `pip install wandb[launch]`.",
)

_logger = logging.getLogger(__name__)

S3_URI_RE = re.compile(r"s3://([^/]+)/(.+)")


class AwsEnvironment(AbstractEnvironment):
    """AWS environment."""

    def __init__(
        self,
        region: str,
        access_key: str,
        secret_key: str,
        session_token: str,
        verify: bool = True,
    ) -> None:
        """Initialize the AWS environment.

        Arguments:
            region (str): The AWS region.

        Raises:
            LaunchError: If the AWS environment is not configured correctly.
        """
        super().__init__()
        _logger.info(f"Initializing AWS environment in region {region}.")
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._account = None
        if verify:
            self.verify()

    @classmethod
    def from_default(cls, region: str, verify: bool = True) -> "AwsEnvironment":
        """Create an AWS environment from the default AWS environment.

        Arguments:
            region (str): The AWS region.
            verify (bool, optional): Whether to verify the AWS environment. Defaults to True.

        Returns:
            AwsEnvironment: The AWS environment.
        """
        _logger.info("Creating AWS environment from default credentials.")
        try:
            session = boto3.Session()
            region = region or session.region_name
            credentials = session.get_credentials()
            if not credentials:
                raise LaunchError(
                    "Could not create AWS environment from default environment. Please verify that your AWS credentials are configured correctly."
                )
            access_key = credentials.access_key
            secret_key = credentials.secret_key
            session_token = credentials.token
        except botocore.client.ClientError as e:
            raise LaunchError(
                f"Could not create AWS environment from default environment. Please verify that your AWS credentials are configured correctly. {e}"
            )
        return cls(
            region=region,
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
            verify=verify,
        )

    @classmethod
    def from_config(
        cls, config: Dict[str, str], verify: bool = True
    ) -> "AwsEnvironment":
        """Create an AWS environment from the default AWS environment.

        Arguments:
            config (dict): Configuration dictionary.
            verify (bool, optional): Whether to verify the AWS environment. Defaults to True.

        Returns:
            AwsEnvironment: The AWS environment.
        """
        region = str(config.get("region", ""))
        if not region:
            raise LaunchError(
                "Could not create AWS environment from config. Region not specified."
            )
        return cls.from_default(
            region=region,
            verify=verify,
        )

    @property
    def region(self) -> str:
        """The AWS region."""
        return self._region

    @region.setter
    def region(self, region: str) -> None:
        self._region = region

    def verify(self) -> None:
        """Verify that the AWS environment is configured correctly.

        Raises:
            LaunchError: If the AWS environment is not configured correctly.
        """
        _logger.debug("Verifying AWS environment.")
        try:
            session = self.get_session()
            client = session.client("sts")
            self._account = client.get_caller_identity().get("Account")
            # TODO: log identity details from the response
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"Could not verify AWS environment. Please verify that your AWS credentials are configured correctly. {e}"
            ) from e

    def get_session(self) -> "boto3.Session":  # type: ignore
        """Get an AWS session.

        Returns:
            boto3.Session: The AWS session.

        Raises:
            LaunchError: If the AWS session could not be created.
        """
        _logger.debug(f"Creating AWS session in region {self._region}")
        try:
            return boto3.Session(
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                aws_session_token=self._session_token,
                region_name=self._region,
            )
        except botocore.exceptions.ClientError as e:
            raise LaunchError(f"Could not create AWS session. {e}")

    def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to s3 from local storage.

        The destination is a valid s3 URI, e.g. s3://bucket/key and will
        be used as a prefix for the uploaded file.  Only the filename of the source
        is kept in the upload key.  So if the source is "foo/bar" and the
        destination is "s3://bucket/key", the file "foo/bar" will be uploaded
        to "s3://bucket/key/bar".

        Arguments:
            source (str): The path to the file or directory.
            destination (str): The uri of the storage destination. This should
                be a valid s3 URI, e.g. s3://bucket/key.

        Raises:
            LaunchError: If the copy fails, the source path does not exist, or the
                destination is not a valid s3 URI, or the upload fails.
        """
        _logger.debug(f"Uploading {source} to {destination}")
        if not os.path.isfile(source):
            raise LaunchError(f"Source {source} does not exist.")
        match = S3_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"Destination {destination} is not a valid s3 URI.")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        if not key:
            key = ""
        session = self.get_session()
        try:
            client = session.client("s3")
            client.upload_file(source, bucket, key)
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"botocore error attempting to copy {source} to {destination}. {e}"
            ) from e

    def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to s3 from local storage.

        The upload will place the contents of the source directory in the destination
        with the same directory structure. So if the source is "foo/bar" and the
        destination is "s3://bucket/key", the contents of "foo/bar" will be uploaded
        to "s3://bucket/key/bar".

        Arguments:
            source (str): The path to the file or directory.
            destination (str): The URI of the storage.
            recursive (bool, optional): If True, copy the directory recursively. Defaults to False.

        Raises:
            LaunchError: If the copy fails, the source path does not exist, or the
                destination is not a valid s3 URI.
        """
        _logger.debug(f"Uploading {source} to {destination}")
        if not os.path.isdir(source):
            raise LaunchError(f"Source {source} does not exist.")
        match = S3_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"Destination {destination} is not a valid s3 URI.")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        if not key:
            key = ""
        session = self.get_session()
        try:
            client = session.client("s3")
            for path, _, files in os.walk(source):
                for file in files:
                    abs_path = os.path.join(path, file)
                    key_path = (
                        abs_path.replace(source, "").replace("\\", "/").lstrip("/")
                    )
                    client.upload_file(
                        abs_path,
                        bucket,
                        key_path,
                    )
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"botocore error attempting to copy {source} to {destination}. {e}"
            ) from e
        except Exception as e:
            raise LaunchError(
                f"Unexpected error attempting to copy {source} to {destination}. {e}"
            ) from e

    def verify_storage_uri(self, uri: str) -> None:
        """Verify that s3 storage is configured correctly.

        This will check that the bucket exists and that the credentials are
        configured correctly.

        Arguments:
            uri (str): The URI of the storage.

        Raises:
            LaunchError: If the storage is not configured correctly or the URI is
                not a valid s3 URI.

        Returns:
            None
        """
        _logger.debug(f"Verifying storage {uri}")
        match = S3_URI_RE.match(uri)
        if not match:
            raise LaunchError(f"Destination {uri} is not a valid s3 URI.")
        bucket = match.group(1)
        try:
            session = self.get_session()
            client = session.client("s3")
            client.head_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"Could not verify AWS storage. Please verify that your AWS credentials are configured correctly. {e}"
            ) from e
