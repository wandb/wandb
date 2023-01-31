import base64
from dataclasses import dataclass
from typing import Tuple

from botocore.exceptions import ClientError

from wandb.errors import LaunchError
from wandb.sdk.launch.environment import AwsEnvironment

from . import AbstractRegistry, RegistryError


@dataclass
class EcrConfig:
    """Elastic Container Registry configuration object.

    Attributes:
        repo (str): The name of the image repository.
    """

    repo: str

    @classmethod
    def from_dict(cls, config_dict: dict):
        """Create an EcrConfig from a dictionary.

        Args:
            config_dict (dict): The dictionary.

        Returns:
            EcrConfig: The EcrConfig.

        Raises:
            RegistryError: If the dictionary is not valid.
        """
        # Check that all required keys are set.
        required_keys = ["repo"]
        for key in required_keys:
            if key not in config_dict:
                raise LaunchError(
                    f"Required key {key} missing in ecr registry config.\n{config_dict}"
                )
        # Check for unknown keys.
        for key in config_dict:
            if key not in required_keys + []:
                raise LaunchError(
                    f"Unknown key {key} in ecr registry config.\n{config_dict}"
                )

        # Construct the config.
        return cls(
            repo=config_dict["repo"],
        )


class ElasticContainerRegistry(AbstractRegistry):
    """Elastic Container Registry class."""

    config: EcrConfig
    environment: AwsEnvironment
    uri: str

    def __init__(self, config, environment):
        super().__init__()
        self.config = config
        self.environment = environment
        self.verify()

    def verify(self):
        """Verify that the registry is accessible and the configured repo exists.

        Raises:
            RegistryError: If there is an error verifying the registry.
        """
        try:
            session = self.environment.get_session()
            client = session.client("ecr")
            response = client.describe_registry()
            response = client.describe_repositories(repositoryNames=[self.config.repo])
            self.uri = response["repositories"][0]["repositoryUri"].split("/")[0]

        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise RegistryError(
                f"Error verifying Elastic Container Registry: {code} {msg}"
            )

    def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            (str, str): The username and password.

        Raises:
            RegistryError: If there is an error getting the username and password.
        """
        try:
            session = self.environment.get_session()
            client = session.client("ecr")
            response = client.get_authorization_token()
            return (
                "AWS",
                base64.standard_b64decode(
                    response["authorizationData"][0]["authorizationToken"]
                )
                .replace(b"AWS:", b"")
                .decode("utf-8"),
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise RegistryError(f"Error getting username and password: {code} {msg}")

    def get_repo_uri(self):
        """Get the uri of the repository.

        Returns:
            str: The uri of the repository.
        """
        return self.uri + "/" + self.config.repo

    def check_exists(self, image_uri):
        """Check if an image exists in the registry.

        Args:
            image_uri (str): The image uri.

        Returns:
            bool: True if the image exists, False otherwise.

        Raises:
            RegistryError: If there is an error checking if the image exists.
        """
        session = self.environment.get_session()
        client = session.client("ecr")
        tag = image_uri.split(":")[1]
        try:
            response = client.describe_images(
                repositoryName=self.config.repo,
                imageIds=[{"imageTag": tag}],
                filter={"tagStatus": "TAGGED"},
            )
            for i in response["imageDetails"]:
                if tag in i["imageTags"]:
                    return True
            return False
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise RegistryError(f"Error checking if image exists: {code} {msg}")
