import os
import re

from wandb.errors import LaunchError
from wandb.util import get_module

from .abstract import AbstractEnvironment

boto3 = get_module("boto3", required="AWS environment requires boto3 to be installed.")
botocore = get_module(
    "botocore", required="AWS environment requires botocore to be installed."
)


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

        Args:
            region (str): The AWS region.

        Raises:
            LaunchError: If the AWS environment is not configured correctly.
        """
        super().__init__()
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        if verify:
            self.verify()

    @classmethod
    def from_default(cls, verify=True):
        """Create an AWS environment from the default AWS environment.

        Returns:
            AwsEnvironment: The AWS environment.
        """
        try:
            session = boto3.Session()
            region = session.region_name
            credentials = session.get_credentials()
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

    def verify(self) -> None:
        """Verify that the AWS environment is configured correctly.

        Raises:
            LaunchError: If the AWS environment is not configured correctly.
        """
        try:
            session = self.get_session()
            client = session.client("sts")
            client.get_caller_identity()
            # TODO: log identity details from the response
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"Could not verify AWS environment. Please verify that your AWS credentials are configured correctly. {e}"
            )

    def verify_storage(self, uri: str) -> None:
        """Verify that storage is configured correctly.

        Args:
            uri (str): The URI of the storage.

        Raises:
            LaunchError: If the storage is not configured correctly.

        Returns:
            None
        """
        bucket = uri.replace("s3://", "").split("/")[0]
        try:
            session = self.get_session()
            client = session.client("s3")
            client.head_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"Could not verify AWS storage. Please verify that your AWS credentials are configured correctly. {e}"
            )

    def get_session(self) -> "boto3.Session":
        """Get an AWS session.

        Returns:
            boto3.Session: The AWS session.

        Raises:
            LaunchError: If the AWS session could not be created.
        """
        try:
            return boto3.Session(
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                aws_session_token=self._session_token,
                region_name=self._region,
            )
        except botocore.exceptions.ClientError as e:
            raise LaunchError(f"Could not create AWS session. {e}")

    def upload(self, source: str, destination: str) -> None:
        """Upload a directory to s3 from local storage.

        The upload will place the contents of the source directory in the destination
        with the same directory structure. So if the source is "foo/bar" and the
        destination is "s3://bucket/key", the contents of "foo/bar" will be uploaded
        to "s3://bucket/key/bar".

        Args:
            source (str): The path to the file or directory.
            destination (str): The URI of the storage.
            recursive (bool, optional): If True, copy the directory recursively. Defaults to False.

        Raises:
            LaunchError: If the copy fails, the source path does not exist, or the
                destination is not a valid s3 URI.
        """
        if not os.path.isdir(source):
            raise LaunchError(f"Source {source} does not exist.")
        match = re.match(r"s3://([^/]+)(/.*)?", destination)
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

                    client.upload_file(
                        abs_path,
                        bucket,
                        f"{key}/{abs_path.replace(source, '').lstrip('/')}",
                    )
        except botocore.exceptions.ClientError as e:
            raise LaunchError(
                f"botocore error attempting to copy {source} to {destination}. {e}"
            )
        except Exception as e:
            raise LaunchError(
                f"Unexpected error attempting to copy {source} to {destination}. {e}"
            )
