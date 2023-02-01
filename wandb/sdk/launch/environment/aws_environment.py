import os
from dataclasses import dataclass
from typing import Optional

from wandb.errors import LaunchError
from wandb.util import get_module


from .abstract import AbstractEnvironment

boto3 = get_module("boto3", required="AWS environment requires boto3 to be installed.")
botocore = get_module(
    "botocore", required="AWS environment requires botocore to be installed."
)


@dataclass
class AwsConfig:
    """AwsEnvironment configuration object.

    Attributes:
        region (str): The AWS region.
        profile (Optional[str], optional): The AWS profile to use. Defaults to None.
        kubernetes_secret (Optional[str], optional): Name of kubernetes secret
            storing aws credentials. If this is not set (default) we will read
            default aws credentials.
    """

    region: str
    profile: Optional[str] = None
    kubernetes_secret: Optional[str] = None

    @classmethod
    def from_dict(cls, config_dict: dict) -> "AwsConfig":
        """Create an AwsConfig from a dictionary.

        Args:
            config_dict (dict): The dictionary.

        Returns:
            AwsConfig: The AwsConfig.

        Raises:
            LaunchError: If the dictionary is not valid.
        """
        # Check that all required keys are set.
        required_keys = ["region"]
        for key in required_keys:
            if key not in config_dict:
                raise LaunchError(
                    f"Required key {key} missing in aws environment config.\n{config_dict}"
                )
        # Check for unknown keys.
        # TODO: Should we error or warn?
        known_keys = required_keys + ["profile", "kubernetes_secret"]
        for key in config_dict:
            if key not in known_keys:
                raise LaunchError(
                    f"Unknown key {key} in aws environment config.\n{config_dict}"
                )

        # Construct the config.
        return cls(
            region=config_dict["region"],
            profile=config_dict.get("profile"),
            kubernetes_secret=config_dict.get("kubernetes_secret"),
        )


class AwsEnvironment(AbstractEnvironment):
    config: AwsConfig

    def __init__(self, config: AwsConfig) -> None:
        """Initialize the AWS environment.

        Args:
            config (AwsConfig): The AWS configuration.

        Raises:
            Exception: If the AWS environment is not configured correctly.
        """
        super().__init__()
        self.config = config
        self.verify()

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
            Exception: If the storage is not configured correctly.

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
            EnvironmentError: If the AWS session could not be created.
        """
        try:
            return boto3.Session(region_name=self.config.region)
        except botocore.exceptions.ClientError as e:
            raise LaunchError(f"Could not create AWS session. {e}")

    def copy(self, source: str, destination: str) -> None:
        """Copy a file or directory to storage.

        Args:
            source (str): The path to the file or directory.
            destination (str): The URI of the storage.
            recursive (bool, optional): If True, copy the directory recursively. Defaults to False.

        Raises:
            EnvironmentError: If the copy fails.
        """
        bucket = destination.replace("s3://", "").split("/")[0]
        key = destination.replace(f"s3://{bucket}/", "")
        session = self.get_session()
        try:
            client = session.client("s3")
            for path, _, files in os.walk(source):
                for file in files:
                    client.upload_file(
                        os.path.join(path, file),
                        bucket,
                        f"{key}/{os.path.join(path, file).replace(source, '')}",
                    )
        except botocore.exceptions.ClientError as e:
            raise LaunchError(f"Could not copy {source} to {destination}. {e}")
