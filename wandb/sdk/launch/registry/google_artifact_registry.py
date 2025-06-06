"""Implementation of Google Artifact Registry for wandb launch."""

import logging
from typing import Optional, Tuple

import google.auth  # type: ignore
import google.cloud.artifactregistry  # type: ignore

from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    GCP_ARTIFACT_REGISTRY_URI_REGEX,
    event_loop_thread_exec,
)
from wandb.util import get_module

from .abstract import AbstractRegistry

_logger = logging.getLogger(__name__)

google = get_module(
    "google",
    required="The google package is required to use launch with Google. Please install it with `pip install wandb[launch]`.",
)
google.auth = get_module(
    "google.auth",
    required="The google-auth package is required to use launch with Google. Please install it with `pip install wandb[launch]`.",
)

google.cloud.artifactregistry = get_module(
    "google.cloud.artifactregistry",
    required="The google-cloud-artifactregistry package is required to use launch with Google. Please install it with `pip install wandb[launch]`.",
)


class GoogleArtifactRegistry(AbstractRegistry):
    """Google Artifact Registry helper for interacting with the registry.

    This helper should be constructed from either a uri or a repository,
    project, and optional image-name. If constructed from a uri, the uri
    must be of the form REGION-docker.pkg.dev/PROJECT/REPOSITORY/[IMAGE_NAME],
    with an optional https:// preceding.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        repository: Optional[str] = None,
        image_name: Optional[str] = None,
        project: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        """Initialize the Google Artifact Registry.

        Either uri or repository and image_name must be provided. Project and
        region are optional, and will be inferred from the uri if provided, or
        from the default credentials if not.

        Arguments:
            uri (optional): The uri of the repository.
            repository (optional): The repository name.
            image_name (optional): The image name.
            project (optional): The GCP project name.
            region (optional): The GCP region name.

        Raises:
            LaunchError: If verify is True and the container registry or its
                environment have not been properly configured. Or if the environment
                is not an instance of GcpEnvironment.
        """
        _logger.info(
            f"Initializing Google Artifact Registry with repository {repository} "
            f"and image name {image_name}"
        )

        if uri is not None:
            self.uri = uri
            # Raise an error if any other kwargs were provided in addition to uri.
            if any([repository, image_name, project, region]):
                raise LaunchError(
                    "The Google Artifact Registry must be specified with either "
                    "the uri key or the repository, image-name, project and region "
                    "keys, but not both."
                )
            match = GCP_ARTIFACT_REGISTRY_URI_REGEX.match(self.uri)
            if not match:
                raise LaunchError(
                    f"The Google Artifact Registry uri {self.uri} is invalid. "
                    "Please provide a uri of the form "
                    "REGION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE_NAME."
                )
            self.project = match.group("project")
            self.region = match.group("region")
            self.repository = match.group("repository")
            self.image_name = match.group("image_name")
        else:
            if any(x is None for x in (repository, region, image_name)):
                raise LaunchError(
                    "The Google Artifact Registry must be specified with either "
                    "the uri key or the repository, image-name, project and region "
                    "keys."
                )
            self.project = project
            self.region = region
            self.repository = repository
            self.image_name = image_name
            self.uri = f"{self.region}-docker.pkg.dev/{self.project}/{self.repository}/{self.image_name}"

        _missing_kwarg_msg = (
            "The Google Artifact Registry is missing the {} kwarg. "
            "Please specify it by name or as part of the uri argument."
        )
        if not self.region:
            raise LaunchError(_missing_kwarg_msg.format("region"))
        if not self.repository:
            raise LaunchError(_missing_kwarg_msg.format("repository"))
        if not self.image_name:
            raise LaunchError(_missing_kwarg_msg.format("image-name"))
        # Try to load default project from the default credentials.
        self.credentials, project = google.auth.default()
        self.project = self.project or project
        self.credentials.refresh(google.auth.transport.requests.Request())

    @classmethod
    def from_config(
        cls,
        config: dict,
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
        # TODO: Replace this with pydantic.
        acceptable_keys = {
            "uri",
            "type",
            "repository",
            "image-name",
            "region",
            "project",
        }
        unacceptable_keys = set(config.keys()) - acceptable_keys
        if unacceptable_keys:
            raise LaunchError(
                f"The Google Artifact Registry config contains unacceptable keys: "
                f"{unacceptable_keys}. Please remove these keys. The acceptable "
                f"keys are: {acceptable_keys}."
            )
        return cls(
            uri=config.get("uri"),
            repository=config.get("repository"),
            image_name=config.get("image-name"),
            project=config.get("project"),
            region=config.get("region"),
        )

    async def get_username_password(self) -> Tuple[str, str]:
        """Get the username and password for the registry.

        Returns:
            A tuple of the username and password.
        """
        if not self.credentials.token:
            self.credentials.refresh(google.auth.transport.requests.Request())
        return "oauth2accesstoken", self.credentials.token

    async def get_repo_uri(self) -> str:
        """Get the URI for the given repository.

        Arguments:
            repo_name: The repository name.

        Returns:
            The repository URI.
        """
        return (
            f"{self.region}-docker.pkg.dev/"
            f"{self.project}/{self.repository}/{self.image_name}"
        )

    async def check_image_exists(self, image_uri: str) -> bool:
        """Check if the image exists.

        Arguments:
            image_uri: The image URI.

        Returns:
            True if the image exists, False otherwise.
        """
        _logger.info(f"Checking if image {image_uri} exists")
        repo_uri, tag = image_uri.split(":")
        self_repo_uri = await self.get_repo_uri()
        if repo_uri != self_repo_uri:
            raise LaunchError(
                f"The image {image_uri} does not match to the image uri "
                f"repository {self.uri}."
            )
        parent = f"projects/{self.project}/locations/{self.region}/repositories/{self.repository}"
        artifact_registry_client = event_loop_thread_exec(
            google.cloud.artifactregistry.ArtifactRegistryClient
        )
        client = await artifact_registry_client(credentials=self.credentials)
        list_images = event_loop_thread_exec(client.list_docker_images)
        try:
            for image in await list_images(request={"parent": parent}):
                if tag in image.tags:
                    return True
        except google.api_core.exceptions.NotFound as e:  # type: ignore[attr-defined]
            raise LaunchError(
                f"The Google Artifact Registry repository {self.repository} "
                f"does not exist. Please create it or modify your registry configuration."
            ) from e
        return False
