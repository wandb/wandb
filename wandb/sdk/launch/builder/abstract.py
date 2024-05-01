"""Abstract plugin class defining the interface needed to build container images for W&B Launch."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry

from .._project_spec import EntryPoint, LaunchProject
from ..registry.anon import AnonynmousRegistry
from ..utils import (
    AZURE_CONTAINER_REGISTRY_URI_REGEX,
    ELASTIC_CONTAINER_REGISTRY_URI_REGEX,
    GCP_ARTIFACT_REGISTRY_URI_REGEX,
)

if TYPE_CHECKING:
    from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker


class AbstractBuilder(ABC):
    """Abstract plugin class defining the interface needed to build container images for W&B Launch."""

    builder_type: str
    environment: AbstractEnvironment
    registry: AbstractRegistry
    builder_config: Dict[str, Any]

    @abstractmethod
    def __init__(
        self,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify: bool = True,
    ) -> None:
        """Initialize a builder.

        Arguments:
            builder_config: The builder config.
            registry: The registry to use.
            verify: Whether to verify the functionality of the builder.

        Raises:
            LaunchError: If the builder cannot be initialized or verified.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_config(
        cls,
        config: dict,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
    ) -> "AbstractBuilder":
        """Create a builder from a config dictionary.

        Arguments:
            config: The config dictionary.
            environment: The environment to use.
            registry: The registry to use.
            verify: Whether to verify the functionality of the builder.
            login: Whether to login to the registry immediately.

        Returns:
            The builder.
        """
        raise NotImplementedError

    @abstractmethod
    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional["JobAndRunStatusTracker"] = None,
    ) -> str:
        """Build the image for the given project.

        Arguments:
            launch_project: The project to build.
            build_ctx_path: The path to the build context.

        Returns:
            The image name.
        """
        raise NotImplementedError

    @abstractmethod
    async def verify(self) -> None:
        """Verify that the builder can be used to build images.

        Raises:
            LaunchError: If the builder cannot be used to build images.
        """
        raise NotImplementedError


def registry_from_uri(uri: str) -> AbstractRegistry:
    """Create a registry helper object from a uri.

    This function parses the URI and determines which supported registry it
    belongs to. It then creates a registry helper object for that registry.
    The supported remote registry types are:
    - Azure Container Registry
    - Google Container Registry
    - AWS Elastic Container Registry

    The format of the URI is as follows:
    - Azure Container Registry: <registry-name>.azurecr.io/<repo-name>/<image-name>
    - Google Container Registry: <location>-docker.pkg.dev/<project-id>/<repo-name>/<image-name>
    - AWS Elastic Container Registry: <account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>/<image-name>

    Our classification of the registry is based on the domain name. For example,
    if the uri contains `.azurecr.io`, we classify it as an Azure
    Container Registry. If the uri contains `.dkr.ecr`, we classify
    it as an AWS Elastic Container Registry. If the uri contains
    `-docker.pkg.dev`, we classify it as a Google Artifact Registry.

    This function will attempt to load the approriate cloud helpers for the

    `https://` prefix is optional for all of the above.

    Arguments:
        uri: The uri to create a registry from.

    Returns:
        The registry.

    Raises:
        LaunchError: If the registry helper cannot be loaded for the given URI.
    """
    if uri.startswith("https://"):
        uri = uri[len("https://") :]

    if AZURE_CONTAINER_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.azure_container_registry import (
            AzureContainerRegistry,
        )

        return AzureContainerRegistry(uri=uri)

    elif GCP_ARTIFACT_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.google_artifact_registry import (
            GoogleArtifactRegistry,
        )

        return GoogleArtifactRegistry(uri=uri)

    elif ELASTIC_CONTAINER_REGISTRY_URI_REGEX.match(uri) is not None:
        from wandb.sdk.launch.registry.elastic_container_registry import (
            ElasticContainerRegistry,
        )

        return ElasticContainerRegistry(uri=uri)

    return AnonynmousRegistry(uri=uri)
