"""Implementation of Google Artifact Registry for wandb launch."""
import logging
import re
from typing import Tuple

from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment
from wandb.sdk.launch.utils import LaunchError
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

        Args:
            repository: The repository name.
            image_name: The image name.
            environment: A GcpEnvironment configured for access to this registry.
            verify: Whether to verify the credentials, region, and project.

        Raises:
            LaunchError: If verify is True and the container registry or its
                environment have not been properly configured.
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
        return "_token", credentials.token
