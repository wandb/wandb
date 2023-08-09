"""Implementation of Elastic Container Registry class for wandb launch."""
import base64
import logging
import re
from typing import Dict, Tuple

import yaml

from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.errors import LaunchError
from wandb.util import get_module

from .abstract import AbstractRegistry

botocore = get_module(
    "botocore",
    required="AWS environment requires botocore to be installed. Please install "
    "it with `pip install wandb[launch]`.",
)

_logger = logging.getLogger(__name__)


class ElasticContainerRegistry(AbstractRegistry):
    """Elastic Container Registry class.

    Attributes:
        repo_name (str): The name of the repository.
        environment (AwsEnvironment): The AWS environment.
        uri (str): The uri of the repository.
    """

    repo_name: str
    environment: AwsEnvironment
    uri: str

    def __init__(self, repo_name: str, environment: AwsEnvironment) -> None:
        """Initialize the Elastic Container Registry.

        Arguments:
            repo_name (str): The name of the repository.
            environment (AwsEnvironment): The AWS environment.

        Raises:
            LaunchError: If there is an error verifying the registry.
        """
        super().__init__()
        _logger.info(
            f"Initializing Elastic Container Registry with repotisory {repo_name}."
        )
        self.repo_name = repo_name
        self.environment = environment
        self.verify()

    @classmethod
    def from_config(  # type: ignore[override]
        cls,
        config: Dict[str, str],
        environment: AwsEnvironment,
        verify: bool = True,
    ) -> "ElasticContainerRegistry":
        """Create an Elastic Container Registry from a config.

        Arguments:
            config (dict): The config.
            environment (AwsEnvironment): The AWS environment.

        Returns:
            ElasticContainerRegistry: The Elastic Container Registry.
        """
        if config.get("type") != "ecr":
            raise LaunchError(
                f"Could not create ElasticContainerRegistry from config. Expected type 'ecr' "
                f"but got '{config.get('type')}'."
            )
        if ("uri" in config) == ("repository" in config):
            raise LaunchError(
                "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                f"'repository' is required. The config received was:\n{yaml.dump(config)}."
            )
        if "repository" in config:
            repository = config.get("repository")
        else:
            match = re.match(
                r"^(?P<account>.*)\.dkr\.ecr\.(?P<region>.*)\.amazonaws\.com/(?P<repository>.*)/?$",
                config["uri"],
            )
            if not match:
                raise LaunchError(
                    f"Could not create ElasticContainerRegistry from config. The uri "
                    f"{config.get('uri')} is invalid."
                )
            repository = match.group("repository")
            if match.group("region") != environment.region:
                raise LaunchError(
                    f"Could not create ElasticContainerRegistry from config. The uri "
                    f"{config.get('uri')} is in region {match.group('region')} but the "
                    f"environment is in region {environment.region}."
                )
            if match.group("account") != environment._account:
                raise LaunchError(
                    f"Could not create ElasticContainerRegistry from config. The uri "
                    f"{config.get('uri')} is in account {match.group('account')} but the "
                    f"account being used is {environment._account}."
                )
        if not isinstance(repository, str):
            # This is for mypy. We should never get here.
            raise LaunchError(
                f"Could not create ElasticContainerRegistry from config. The repository "
                f"{repository} is invalid: repository should be a string."
            )
        return cls(repository, environment)

    def verify(self) -> None:
        """Verify that the registry is accessible and the configured repo exists.

        Raises:
            RegistryError: If there is an error verifying the registry.
        """
        _logger.debug("Verifying Elastic Container Registry.")
        try:
            session = self.environment.get_session()
            client = session.client("ecr")
            response = client.describe_repositories(repositoryNames=[self.repo_name])
            self.uri = response["repositories"][0]["repositoryUri"].split("/")[0]

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise LaunchError(
                f"Error verifying Elastic Container Registry: {code} {msg}"
            )

    def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            (str, str): The username and password.

        Raises:
            RegistryError: If there is an error getting the username and password.
        """
        _logger.debug("Getting username and password for Elastic Container Registry.")
        try:
            session = self.environment.get_session()
            client = session.client("ecr")
            response = client.get_authorization_token()
            username, password = base64.standard_b64decode(
                response["authorizationData"][0]["authorizationToken"]
            ).split(b":")
            return username.decode("utf-8"), password.decode("utf-8")

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise LaunchError(f"Error getting username and password: {code} {msg}")

    def get_repo_uri(self) -> str:
        """Get the uri of the repository.

        Returns:
            str: The uri of the repository.
        """
        return self.uri + "/" + self.repo_name

    def check_image_exists(self, image_uri: str) -> bool:
        """Check if the image tag exists.

        Arguments:
            image_uri (str): The full image_uri.

        Returns:
            bool: True if the image tag exists.
        """
        uri, tag = image_uri.split(":")
        if uri != self.get_repo_uri():
            raise LaunchError(
                f"Image uri {image_uri} does not match Elastic Container Registry uri {self.get_repo_uri()}."
            )

        _logger.debug("Checking if image tag exists.")
        try:
            session = self.environment.get_session()
            client = session.client("ecr")
            response = client.describe_images(
                repositoryName=self.repo_name, imageIds=[{"imageTag": tag}]
            )
            return len(response["imageDetails"]) > 0

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ImageNotFoundException":
                return False
            msg = e.response["Error"]["Message"]
            raise LaunchError(f"Error checking if image tag exists: {code} {msg}")
