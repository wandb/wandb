"""Implementation of Google Artifact Registry for wandb launch."""
import logging
import re
from typing import Tuple

import yaml

from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment
from wandb.sdk.launch.errors import LaunchError
from wandb.util import get_module

from .abstract import AbstractRegistry

google = get_module(
    "google",
    required="Google Cloud Platform support requires the google package. Please"
    " install it with `pip install wandb[launch]`.",
)

google.cloud.artifactregistry = get_module(
    "google.cloud.artifactregistry",
    required="Google Cloud Platform support requires the google-cloud-artifact-registry package. "
    "Please install it with `pip install wandb[launch]`.",
)

google.auth.credentials = get_module(
    "google.auth.credentials",
    required="Google Cloud Platform support requires google-auth. "
    "Please install it with `pip install wandb[launch]`.",
)

_logger = logging.getLogger(__name__)


class GoogleArtifactRegistry(AbstractRegistry):
    """Google Artifact Registry.

    Attributes:
        repository: The repository name.
        environment: A GcpEnvironment configured for access to this registry.
    """

    repository: str
    image_name: str
    environment: GcpEnvironment

    def __init__(
        self,
        repository: str,
        image_name: str,
        environment: GcpEnvironment,
        verify: bool = True,
    ) -> None:
        """Initialize the Google Artifact Registry.

        Arguments:
            repository: The repository name.
            image_name: The image name.
            environment: A GcpEnvironment configured for access to this registry.
            verify: Whether to verify the credentials, region, and project.

        Raises:
            LaunchError: If verify is True and the container registry or its
                environment have not been properly configured. Or if the environment
                is not an instance of GcpEnvironment.
        """
        _logger.info(
            f"Initializing Google Artifact Registry with repository {repository} "
            f"and image name {image_name}"
        )
        self.repository = repository
        self.image_name = image_name
        if not re.match(r"^\w[\w.-]+$", image_name):
            raise LaunchError(
                f"The image name {image_name} is invalid. The image name must "
                "consist of alphanumeric characters and underscores."
            )
        self.environment = environment
        if verify:
            self.verify()

    @property
    def uri(self) -> str:
        """The uri of the registry."""
        return f"{self.environment.region}-docker.pkg.dev/{self.environment.project}/{self.repository}/{self.image_name}"

    @uri.setter
    def uri(self, uri: str) -> None:
        """Set the uri of the registry."""
        raise LaunchError("The uri of the Google Artifact Registry cannot be set.")

    @classmethod
    def from_config(  # type: ignore[override]
        cls,
        config: dict,
        environment: GcpEnvironment,
        verify: bool = True,
    ) -> "GoogleArtifactRegistry":
        """Create a Google Artifact Registry from a config.

        Arguments:
            config: A dictionary containing the following keys:
                repository: The repository name.
                image-name: The image name.
            environment: A GcpEnvironment configured for access to this registry.

        Returns:
            A GoogleArtifactRegistry.
        """
        if "uri" in config:
            if "repository" in config or "image-name" in config:
                raise LaunchError(
                    "The Google Artifact Registry must be specified with either "
                    "the uri key or the repository and image-name keys, but not both. "
                    f"The provided config is:\n{yaml.dump(config)}."
                )
            match = re.match(
                r"^(?P<region>[\w-]+)-docker\.pkg\.dev/(?P<project>[\w-]+)/(?P<repository>[\w-]+)/(?P<image_name>[\w-]+)$",
                config["uri"],
            )
            if not match:
                raise LaunchError(
                    f"The Google Artifact Registry uri {config['uri']} is invalid. "
                    "Please provide a uri of the form "
                    "REGION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE_NAME."
                )
            else:
                repository = match.group("repository")
                image_name = match.group("image_name")
                if match.group("region") != environment.region:
                    raise LaunchError(
                        f"The Google Artifact Registry uri {config['uri']} does not "
                        f"match the configured region {environment.region}."
                    )
                if match.group("project") != environment.project:
                    raise LaunchError(
                        f"The Google Artifact Registry uri {config['uri']} does not "
                        f"match the configured project {environment.project}."
                    )
        else:
            repository = config.get("repository")
            if not repository:
                raise LaunchError(
                    "The Google Artifact Registry repository must be specified "
                    "by setting the either the uri or  repository key of your "
                    f"registry config. The provided config is:\n{yaml.dump(config)}."
                )
            image_name = config.get("image-name")
            if not image_name:
                raise LaunchError(
                    "The Google Artifact Registry repository must be specified "
                    "by setting the either the uri or  repository key of your "
                    f"registry config. The provided config is:\n{yaml.dump(config)}."
                )
        return cls(repository, image_name, environment, verify=verify)

    def verify(self) -> None:
        """Verify the registry is properly configured.

        Raises:
            LaunchError: If the registry is not properly configured.
        """
        credentials = self.environment.get_credentials()
        parent = (
            f"projects/{self.environment.project}/locations/{self.environment.region}"
        )
        # We need to list the repositories to verify that the repository exists.
        request = google.cloud.artifactregistry.ListRepositoriesRequest(parent=parent)
        client = google.cloud.artifactregistry.ArtifactRegistryClient(
            credentials=credentials
        )
        try:
            response = client.list_repositories(request=request)
        except google.api_core.exceptions.PermissionDenied:
            raise LaunchError(
                "The provided credentials do not have permission to access the "
                f"Google Artifact Registry repository {self.repository}."
            )
        # Look for self.repository in the list of responses.
        for repo in response:
            if repo.name.endswith(self.repository):
                break
        # If we didn't find the repository, raise an error.
        else:
            raise LaunchError(
                f"The Google Artifact Registry repository {self.repository} does not exist."
            )

    def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            A tuple of the username and password.
        """
        credentials = self.environment.get_credentials()
        return "oauth2accesstoken", credentials.token

    def get_repo_uri(self) -> str:
        """Get the URI for the given repository.

        Arguments:
            repo_name: The repository name.

        Returns:
            The repository URI.
        """
        return (
            f"{self.environment.region}-docker.pkg.dev/"
            f"{self.environment.project}/{self.repository}/{self.image_name}"
        )

    def check_image_exists(self, image_uri: str) -> bool:
        """Check if the image exists.

        Arguments:
            image_uri: The image URI.

        Returns:
            True if the image exists, False otherwise.
        """
        _logger.info(
            f"Checking if image {image_uri} exists. In Google Artifact Registry {self.uri}."
        )
        repo_uri, tag = image_uri.split(":")
        if repo_uri != self.get_repo_uri():
            raise LaunchError(
                f"The image {image_uri} does not belong to the Google Artifact "
                f"Repository {self.get_repo_uri()}."
            )
        credentials = self.environment.get_credentials()

        # request = google.cloud.artifactregistry.GetTagRequest(name=image_uri)
        parent = f"projects/{self.environment.project}/locations/{self.environment.region}/repositories/{self.repository}"
        client = google.cloud.artifactregistry.ArtifactRegistryClient(
            credentials=credentials
        )
        try:
            for image in client.list_docker_images(request={"parent": parent}):
                if tag in image.tags:
                    return True
        except google.api_core.exceptions.NotFound as e:
            raise LaunchError(
                f"The Google Artifact Registry repository {self.repository} does not exist."
            ) from e
        return False
