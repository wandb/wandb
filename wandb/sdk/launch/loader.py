"""Utilities for the agent."""

from typing import Any, Dict, Optional

import wandb
from wandb.apis.internal import Api
from wandb.docker import is_docker_installed
from wandb.sdk.launch.errors import LaunchError

from .builder.abstract import AbstractBuilder
from .environment.abstract import AbstractEnvironment
from .registry.abstract import AbstractRegistry
from .runner.abstract import AbstractRunner

WANDB_RUNNERS = {
    "local-container",
    "local-process",
    "kubernetes",
    "vertex",
    "sagemaker",
}


def environment_from_config(config: Optional[Dict[str, Any]]) -> AbstractEnvironment:
    """Create an environment from a config.

    This helper function is used to create an environment from a config. The
    config should have a "type" key that specifies the type of environment to
    create. The remaining keys are passed to the environment's from_config
    method. If the config is None or empty, a LocalEnvironment is returned.

    Arguments:
        config (Dict[str, Any]): The config.

    Returns:
        Environment: The environment constructed.
    """
    if not config:
        from .environment.local_environment import LocalEnvironment

        return LocalEnvironment()  # This is the default, dummy environment.
    env_type = config.get("type")
    if not env_type:
        raise LaunchError(
            "Could not create environment from config. Environment type not specified!"
        )
    if env_type == "local":
        from .environment.local_environment import LocalEnvironment

        return LocalEnvironment.from_config(config)
    if env_type == "aws":
        from .environment.aws_environment import AwsEnvironment

        return AwsEnvironment.from_config(config)
    if env_type == "gcp":
        from .environment.gcp_environment import GcpEnvironment

        return GcpEnvironment.from_config(config)
    if env_type == "azure":
        from .environment.azure_environment import AzureEnvironment

        return AzureEnvironment.from_config(config)
    raise LaunchError(
        f"Could not create environment from config. Invalid type: {env_type}"
    )


def registry_from_config(
    config: Optional[Dict[str, Any]], environment: AbstractEnvironment
) -> AbstractRegistry:
    """Create a registry from a config.

    This helper function is used to create a registry from a config. The
    config should have a "type" key that specifies the type of registry to
    create. The remaining keys are passed to the registry's from_config
    method. If the config is None or empty, a LocalRegistry is returned.

    Arguments:
        config (Dict[str, Any]): The registry config.
        environment (Environment): The environment of the registry.

    Returns:
        The registry if config is not None, otherwise None.

    Raises:
        LaunchError: If the registry is not configured correctly.
    """
    if not config:
        from .registry.local_registry import LocalRegistry

        return LocalRegistry()  # This is the default, dummy registry.

    wandb.termwarn(
        "The `registry` block of the launch agent config is being deprecated. "
        "Please specify an image repository URI under the `builder.destination` "
        "key of your launch agent config. See "
        "https://docs.wandb.ai/guides/launch/setup-agent-advanced#agent-configuration "
        "for more information."
    )

    registry_type = config.get("type")
    if registry_type is None or registry_type == "local":
        from .registry.local_registry import LocalRegistry

        return LocalRegistry()  # This is the default, dummy registry.
    if registry_type == "ecr":
        from .registry.elastic_container_registry import ElasticContainerRegistry

        return ElasticContainerRegistry.from_config(config)
    if registry_type == "gcr":
        from .registry.google_artifact_registry import GoogleArtifactRegistry

        return GoogleArtifactRegistry.from_config(config)
    if registry_type == "acr":
        from .registry.azure_container_registry import AzureContainerRegistry

        return AzureContainerRegistry.from_config(config)
    raise LaunchError(
        f"Could not create registry from config. Invalid registry type: {registry_type}"
    )


def builder_from_config(
    config: Optional[Dict[str, Any]],
    environment: AbstractEnvironment,
    registry: AbstractRegistry,
) -> AbstractBuilder:
    """Create a builder from a config.

    This helper function is used to create a builder from a config. The
    config should have a "type" key that specifies the type of builder to import
    and create. The remaining keys are passed to the builder's from_config
    method. If the config is None or empty, a default builder is returned.

    The default builder will be a DockerBuilder if we find a working docker cli
    on the system, otherwise it will be a NoOpBuilder.

    Arguments:
        config (Dict[str, Any]): The builder config.
        registry (Registry): The registry of the builder.

    Returns:
        The builder.

    Raises:
        LaunchError: If the builder is not configured correctly.
    """
    if not config:
        if is_docker_installed():
            from .builder.docker_builder import DockerBuilder

            return DockerBuilder.from_config(
                {}, environment, registry
            )  # This is the default builder.

        from .builder.noop import NoOpBuilder

        return NoOpBuilder.from_config({}, environment, registry)

    builder_type = config.get("type")
    if builder_type is None:
        raise LaunchError(
            "Could not create builder from config. Builder type not specified"
        )
    if builder_type == "docker":
        from .builder.docker_builder import DockerBuilder

        return DockerBuilder.from_config(config, environment, registry)
    if builder_type == "kaniko":
        from .builder.kaniko_builder import KanikoBuilder

        return KanikoBuilder.from_config(config, environment, registry)
    if builder_type == "noop":
        from .builder.noop import NoOpBuilder

        return NoOpBuilder.from_config(config, environment, registry)
    raise LaunchError(
        f"Could not create builder from config. Invalid builder type: {builder_type}"
    )


def runner_from_config(
    runner_name: str,
    api: Api,
    runner_config: Dict[str, Any],
    environment: AbstractEnvironment,
    registry: AbstractRegistry,
) -> AbstractRunner:
    """Create a runner from a config.

    This helper function is used to create a runner from a config. The
    config should have a "type" key that specifies the type of runner to import
    and create. The remaining keys are passed to the runner's from_config
    method. If the config is None or empty, a LocalContainerRunner is returned.

    Arguments:
        runner_name (str): The name of the backend.
        api (Api): The API.
        runner_config (Dict[str, Any]): The backend config.

    Returns:
        The runner.

    Raises:
        LaunchError: If the runner is not configured correctly.
    """
    if not runner_name or runner_name in ["local-container", "local"]:
        from .runner.local_container import LocalContainerRunner

        return LocalContainerRunner(api, runner_config, environment, registry)
    if runner_name == "local-process":
        from .runner.local_process import LocalProcessRunner

        return LocalProcessRunner(api, runner_config)
    if runner_name == "sagemaker":
        from .environment.aws_environment import AwsEnvironment

        if not isinstance(environment, AwsEnvironment):
            try:
                environment = AwsEnvironment.from_default()
            except LaunchError as e:
                raise LaunchError(
                    "Could not create Sagemaker runner. "
                    "Environment must be an instance of AwsEnvironment."
                ) from e
        from .runner.sagemaker_runner import SageMakerRunner

        return SageMakerRunner(api, runner_config, environment, registry)
    if runner_name in ["vertex", "gcp-vertex"]:
        from .environment.gcp_environment import GcpEnvironment

        if not isinstance(environment, GcpEnvironment):
            try:
                environment = GcpEnvironment.from_default()
            except LaunchError as e:
                raise LaunchError(
                    "Could not create Vertex runner. "
                    "Environment must be an instance of GcpEnvironment."
                ) from e
        from .runner.vertex_runner import VertexRunner

        return VertexRunner(api, runner_config, environment, registry)
    if runner_name == "kubernetes":
        from .runner.kubernetes_runner import KubernetesRunner

        return KubernetesRunner(api, runner_config, environment, registry)
    raise LaunchError(
        f"Could not create runner from config. Invalid runner name: {runner_name}"
    )
