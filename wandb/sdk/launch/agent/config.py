"""Definition of the config object used by the Launch agent."""

from enum import Enum
from typing import List, Optional

# ValidationError is imported for exception type checking purposes only.
from pydantic import (  # type: ignore
    BaseModel,
    Field,
    ValidationError,  # noqa: F401
    root_validator,
    validator,
)

import wandb
from wandb.sdk.launch.utils import (
    AZURE_BLOB_REGEX,
    AZURE_CONTAINER_REGISTRY_URI_REGEX,
    ELASTIC_CONTAINER_REGISTRY_URI_REGEX,
    GCP_ARTIFACT_REGISTRY_URI_REGEX,
    GCS_URI_RE,
    S3_URI_RE,
)

__all__ = [
    "ValidationError",
    "AgentConfig",
]


class EnvironmentType(str, Enum):
    """Enum of valid environment types."""

    aws = "aws"
    gcp = "gcp"
    azure = "azure"


class RegistryType(str, Enum):
    """Enum of valid registry types."""

    ecr = "ecr"
    acr = "acr"
    gcr = "gcr"


class BuilderType(str, Enum):
    """Enum of valid builder types."""

    docker = "docker"
    kaniko = "kaniko"
    noop = "noop"


class TargetPlatform(str, Enum):
    """Enum of valid target platforms."""

    linux_amd64 = "linux/amd64"
    linux_arm64 = "linux/arm64"


class RegistryConfig(BaseModel):
    """Configuration for registry block.

    Note that we don't forbid extra fields here because:
    - We want to allow all fields supported by each registry
    - We will perform validation on the registry object itself later
    - Registry block is being deprecated in favor of destination field in builder
    """

    type: Optional[RegistryType] = Field(
        None,
        description="The type of registry to use.",
    )
    uri: Optional[str] = Field(
        None,
        description="The URI of the registry.",
    )

    @validator("uri")  # type: ignore
    @classmethod
    def validate_uri(cls, uri: str) -> str:
        return validate_registry_uri(uri)


class EnvironmentConfig(BaseModel):
    """Configuration for the environment block."""

    type: Optional[EnvironmentType] = Field(
        None,
        description="The type of environment to use.",
    )
    region: Optional[str] = Field(..., description="The region to use.")

    class Config:
        extra = "allow"

    @root_validator(pre=True)  # type: ignore
    @classmethod
    def check_extra_fields(cls, values: dict) -> dict:
        """Check for extra fields and print a warning."""
        for key in values:
            if key not in ["type", "region"]:
                wandb.termwarn(
                    f"Unrecognized field {key} in environment block. Please check your config file."
                )
        return values


class BuilderConfig(BaseModel):
    type: Optional[BuilderType] = Field(
        None,
        description="The type of builder to use.",
    )
    destination: Optional[str] = Field(
        None,
        description="The destination to use for the built image. If not provided, "
        "the image will be pushed to the registry.",
    )

    platform: Optional[TargetPlatform] = Field(
        None,
        description="The platform to use for the built image. If not provided, "
        "the platform will be detected automatically.",
    )

    build_context_store: Optional[str] = Field(
        None,
        description="The build context store to use. Required for kaniko builds.",
        alias="build-context-store",
    )
    build_job_name: Optional[str] = Field(
        "wandb-launch-container-build",
        description="Name prefix of the build job.",
        alias="build-job-name",
    )
    secret_name: Optional[str] = Field(
        None,
        description="The name of the secret to use for the build job.",
        alias="secret-name",
    )
    secret_key: Optional[str] = Field(
        None,
        description="The key of the secret to use for the build job.",
        alias="secret-key",
    )
    kaniko_image: Optional[str] = Field(
        "gcr.io/kaniko-project/executor:latest",
        description="The image to use for the kaniko executor.",
        alias="kaniko-image",
    )

    @validator("build_context_store")  # type: ignore
    @classmethod
    def validate_build_context_store(
        cls, build_context_store: Optional[str]
    ) -> Optional[str]:
        """Validate that the build context store is a valid container registry URI."""
        if build_context_store is None:
            return None
        for regex in [
            S3_URI_RE,
            GCS_URI_RE,
            AZURE_BLOB_REGEX,
        ]:
            if regex.match(build_context_store):
                return build_context_store
        raise ValueError(
            "Invalid build context store. Build context store must be a URI for an "
            "S3 bucket, GCS bucket, or Azure blob."
        )

    @root_validator(pre=True)  # type: ignore
    @classmethod
    def validate_docker(cls, values: dict) -> dict:
        """Right now there are no required fields for docker builds."""
        return values

    @validator("destination")  # type: ignore
    @classmethod
    def validate_destination(cls, destination: Optional[str]) -> Optional[str]:
        """Validate that the destination is a valid container registry URI."""
        if destination is None:
            return None
        return validate_registry_uri(destination)


class AgentConfig(BaseModel):
    """Configuration for the Launch agent."""

    queues: List[str] = Field(
        default=[],
        description="The queues to use for this agent.",
    )
    entity: Optional[str] = Field(
        description="The W&B entity to use for this agent.",
    )
    max_jobs: Optional[int] = Field(
        1,
        description="The maximum number of jobs to run concurrently.",
    )
    max_schedulers: Optional[int] = Field(
        1,
        description="The maximum number of sweep schedulers to run concurrently.",
    )
    secure_mode: Optional[bool] = Field(
        False,
        description="Whether to use secure mode for this agent. If True, the "
        "agent will reject runs that attempt to override the entrypoint or image.",
    )
    registry: Optional[RegistryConfig] = Field(
        None,
        description="The registry to use.",
    )
    environment: Optional[EnvironmentConfig] = Field(
        None,
        description="The environment to use.",
    )
    builder: Optional[BuilderConfig] = Field(
        None,
        description="The builder to use.",
    )
    verbosity: Optional[int] = Field(
        0,
        description="How verbose to print, 0 = default, 1 = verbose, 2 = very verbose",
    )
    stopped_run_timeout: Optional[int] = Field(
        60,
        description="How many seconds to wait after receiving the stop command before forcibly cancelling a run.",
    )

    class Config:
        extra = "forbid"


def validate_registry_uri(uri: str) -> str:
    """Validate that the registry URI is a valid container registry URI.

    The URI should resolve to an image name in a container registry. The recognized
    formats are for ECR, ACR, and GCP Artifact Registry. If the URI does not match
    any of these formats, a warning is printed indicating the registry type is not
    recognized and the agent can't guarantee that images can be pushed.

    If the format is recognized but does not resolve to an image name, an
    error is raised. For example, if the URI is an ECR URI but does not include
    an image name or includes a tag as well as an image name, an error is raised.
    """
    tag_msg = (
        "Destination for built images may not include a tag, but the URI provided "
        "includes the suffix '{tag}'. Please remove the tag and try again. The agent "
        "will automatically tag each image with a unique hash of the source code."
    )
    if uri.startswith("https://"):
        uri = uri[8:]

    match = GCP_ARTIFACT_REGISTRY_URI_REGEX.match(uri)
    if match:
        if match.group("tag"):
            raise ValueError(tag_msg.format(tag=match.group("tag")))
        if not match.group("image_name"):
            raise ValueError(
                "An image name must be specified in the URI for a GCP Artifact Registry. "
                "Please provide a uri with the format "
                "'https://<region>-docker.pkg.dev/<project>/<repository>/<image>'."
            )
        return uri

    match = AZURE_CONTAINER_REGISTRY_URI_REGEX.match(uri)
    if match:
        if match.group("tag"):
            raise ValueError(tag_msg.format(tag=match.group("tag")))
        if not match.group("repository"):
            raise ValueError(
                "A repository name must be specified in the URI for an "
                "Azure Container Registry. Please provide a uri with the format "
                "'https://<registry-name>.azurecr.io/<repository>'."
            )
        return uri

    match = ELASTIC_CONTAINER_REGISTRY_URI_REGEX.match(uri)
    if match:
        if match.group("tag"):
            raise ValueError(tag_msg.format(tag=match.group("tag")))
        if not match.group("repository"):
            raise ValueError(
                "A repository name must be specified in the URI for an "
                "Elastic Container Registry. Please provide a uri with the format "
                "'https://<account-id>.dkr.ecr.<region>.amazonaws.com/<repository>'."
            )
        return uri

    wandb.termwarn(
        f"Unable to recognize registry type in URI {uri}. You are responsible "
        "for ensuring the agent can push images to this registry."
    )
    return uri
