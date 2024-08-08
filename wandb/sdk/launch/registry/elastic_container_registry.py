"""Implementation of Elastic Container Registry class for wandb launch."""

import base64
import logging
from typing import Dict, Optional, Tuple

from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.utils import (
    ELASTIC_CONTAINER_REGISTRY_URI_REGEX,
    event_loop_thread_exec,
)
from wandb.util import get_module

_logger = logging.getLogger(__name__)

botocore = get_module(  # noqa: F811
    "botocore",
    required="The boto3 package is required to use launch with AWS. Please install it with `pip install wandb[launch]`.",
)
boto3 = get_module(  # noqa: F811
    "boto3",
    required="The boto3 package is required to use launch with AWS. Please install it with `pip install wandb[launch]`.",
)


class ElasticContainerRegistry(AbstractRegistry):
    """Elastic Container Registry class."""

    def __init__(
        self,
        uri: Optional[str] = None,
        account_id: Optional[str] = None,
        region: Optional[str] = None,
        repo_name: Optional[str] = None,
    ) -> None:
        """Initialize the Elastic Container Registry.

        Arguments:
            uri: The uri of the repository.
            account_id: The AWS account id.
            region: The AWS region of the container registry.
            repository: The name of the repository.

        Raises:
            LaunchError: If there is an error initializing the Elastic Container Registry helper.
        """
        if uri:
            self.uri = uri
            if any([account_id, region, repo_name]):
                raise LaunchError(
                    "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                    "'account_id', 'region', and 'repo_name' are required."
                )
            match = ELASTIC_CONTAINER_REGISTRY_URI_REGEX.match(
                self.uri,
            )
            if not match:
                raise LaunchError(
                    f"Could not create ElasticContainerRegistry from config. The uri "
                    f"{self.uri} is invalid."
                )
            self.account_id = match.group("account")
            self.region = match.group("region")
            self.repo_name = match.group("repository")
        else:
            if not all([account_id, region, repo_name]):
                raise LaunchError(
                    "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                    "'account_id', 'region', and 'repo_name' are required."
                )
            self.account_id = account_id
            self.region = region
            self.repo_name = repo_name
            self.uri = f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.repo_name}"
        if self.account_id is None:
            raise LaunchError(
                "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                "'account_id' is required."
            )
        if self.region is None:
            raise LaunchError(
                "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                "'region' is required."
            )
        if self.repo_name is None:
            raise LaunchError(
                "Could not create ElasticContainerRegistry from config. Either 'uri' or "
                "'repository' is required."
            )

    @classmethod
    def from_config(
        cls,
        config: Dict[str, str],
    ) -> "ElasticContainerRegistry":
        """Create an Elastic Container Registry from a config.

        Arguments:
            config (dict): The config.

        Returns:
            ElasticContainerRegistry: The Elastic Container Registry.
        """
        # TODO: Replace this with pydantic.
        acceptable_keys = {
            "uri",
            "type",
            "account_id",
            "region",
            "repo_name",
        }
        unsupported_keys = set(config.keys()) - acceptable_keys
        if unsupported_keys:
            raise LaunchError(
                f"The Elastic Container Registry config contains unsupported keys: "
                f"{unsupported_keys}. Please remove these keys. The acceptable "
                f"keys are: {acceptable_keys}."
            )
        return cls(
            uri=config.get("uri"),
            account_id=config.get("account_id"),
            region=config.get("region"),
            repo_name=config.get("repository"),
        )

    async def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            (str, str): The username and password.

        Raises:
            RegistryError: If there is an error getting the username and password.
        """
        _logger.debug("Getting username and password for Elastic Container Registry.")
        try:
            session = boto3.Session(region_name=self.region)
            client = await event_loop_thread_exec(session.client)("ecr")
            response = await event_loop_thread_exec(client.get_authorization_token)()
            username, password = base64.standard_b64decode(
                response["authorizationData"][0]["authorizationToken"]
            ).split(b":")
            return username.decode("utf-8"), password.decode("utf-8")

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            # TODO: Log the code and the message here?
            raise LaunchError(f"Error getting username and password: {code} {msg}")

    async def get_repo_uri(self) -> str:
        """Get the uri of the repository.

        Returns:
            str: The uri of the repository.
        """
        return f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{self.repo_name}"

    async def check_image_exists(self, image_uri: str) -> bool:
        """Check if the image tag exists.

        Arguments:
            image_uri (str): The full image_uri.

        Returns:
            bool: True if the image tag exists.
        """
        if ":" not in image_uri:
            tag = image_uri
        else:
            uri, tag = image_uri.split(":")
            repo_uri = await self.get_repo_uri()
            if uri != repo_uri:
                raise LaunchError(
                    f"Image uri {image_uri} does not match Elastic Container Registry uri {repo_uri}."
                )
        _logger.debug(f"Checking if image tag {tag} exists in repository {self.uri}")
        try:
            session = boto3.Session(region_name=self.region)
            client = await event_loop_thread_exec(session.client)("ecr")
            response = await event_loop_thread_exec(client.describe_images)(
                repositoryName=self.repo_name, imageIds=[{"imageTag": tag}]
            )
            return len(response["imageDetails"]) > 0

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ImageNotFoundException":
                return False
            msg = e.response["Error"]["Message"]
            raise LaunchError(f"Error checking if image tag exists: {code} {msg}")
