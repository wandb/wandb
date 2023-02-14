"""Utilities for the agent."""
from typing import Any, Dict, Optional

from wandb.errors import LaunchError
from wandb.util import get_module
from wandb.apis.internal import Api
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.builder.abstract import AbstractBuilder


def environment_from_config(config: Optional[Dict[str, Any]]) -> AbstractEnvironment:
    """Create an environment from a config.

    This helper function is used to create an environment from a config. The
    config should have a "type" key that specifies the type of environment to
    create. The remaining keys are passed to the environment's from_config
    method.

    Args:
        config (Dict[str, Any]): The config.
    Returns:
        Environment: The environment.
    Raises:
        LaunchError: If the environment is not configured correctly.
    """
    env_type = config.get("type")
    if env_type is None:
        return None
    if env_type == "aws":
        module = get_module("wandb.sdk.launch.environment.aws_environment")
        return module.AwsEnvironment.from_config(config)
    if env_type == "gcp":
        module = get_module("wandb.sdk.launch.environment.gcp_environment")
        return module.GcpEnvironment.from_config(config)
    raise LaunchError("Could not create environment from config.")


def registry_from_config(
    config: Optional[Dict[str, Any]], environment: AbstractEnvironment
) -> AbstractRegistry:
    """Create a registry from a config.

    This helper function is used to create a registry from a config. The
    config should have a "type" key that specifies the type of registry to
    create. The remaining keys are passed to the registry's from_config
    method.

    Args:
        config (Dict[str, Any]): The registry config.
        environment (Environment): The environment of the registry.

    Returns:
        The registry.

    Raises:
        LaunchError: If the registry is not configured correctly.
    """
    registry_type = config.get("type")
    if registry_type is None:
        return None
    if registry_type == "ecr":
        module = get_module("wandb.sdk.launch.registry.elastic_container_registry")
        return module.ElasticContainerRegistry.from_config(config, environment)
    if registry_type == "gcr":
        module = get_module("wandb.sdk.launch.registry.google_artifact_registry")
        return module.GoogleArtifactRegistry.from_config(config, environment)
    raise LaunchError("Could not create registry from config.")


def builder_from_config(
    config: Optional[Dict[str, Any]],
    environment: AbstractEnvironment,
    registry: AbstractRegistry,
) -> AbstractBuilder:
    """Create a builder from a config.

    This helper function is used to create a builder from a config. The
    config should have a "type" key that specifies the type of builder to import
    and create. The remaining keys are passed to the builder's from_config
    method.

    Args:
        config (Dict[str, Any]): The builder config.
        registry (Registry): The registry of the builder.

    Returns:
        The builder.

    Raises:
        LaunchError: If the builder is not configured correctly.
    """
    builder_type = config.get("type")
    if builder_type == "docker" or not builder_type:
        module = get_module("wandb.sdk.launch.builder.docker_builder")
        return module.DockerBuilder.from_config(config, environment, registry)
    if builder_type == "kaniko":
        module = get_module("wandb.sdk.launch.builder.kaniko_builder")
        return module.KanikoBuilder.from_config(config, environment, registry)
    if builder_type == "noop":
        module = get_module("wandb.sdk.launch.builder.noop")
        return module.NoOpBuilder.from_config(config, environment, registry)
    raise LaunchError("Could not create builder from config.")


def runner_from_config(
    runner_name: str,
    api: Api,
    runer_config: Dict[str, Any],
    environment: AbstractEnvironment,
):
    """Create a runner from a config.

    This helper function is used to create a runner from a config. The
    config should have a "type" key that specifies the type of runner to import
    and create. The remaining keys are passed to the runner's from_config
    method.

    Args:
        runner_name (str): The name of the backend.
        api (Api): The API.
        runner_config (Dict[str, Any]): The backend config.

    Returns:
        The runner.

    Raises:
        LaunchError: If the runner is not configured correctly.
    """
    if runner_name == "local-container" or not runner_name:
        module = get_module("wandb.sdk.launch.runner.local_container")
        return module.LocalContainerRunner(api, runer_config, environment)
    if runner_name == "local-process":
        module = get_module("wandb.sdk.launch.runner.local_process")
        return module.LocalProcessRunner(api, runer_config, environment)
    if runner_name == "sagemaker":
        module = get_module("wandb.sdk.launch.runner.sagemaker_runner")
        return module.SagemakerRunner(api, runer_config, environment)
    if runner_name == "vertex":
        module = get_module("wandb.sdk.launch.runner.vertex_runner")
        return module.GcpRunner(api, runer_config, environment)
    if runner_name == "kubernetes":
        module = get_module("wandb.sdk.launch.runner.kubernetes_runner")
        return module.KubernetesRunner(api, runer_config, environment)
    raise LaunchError("Could not create runner from config.")
