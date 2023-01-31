from wandb.errors import LaunchError


class RegistryError(LaunchError):
    pass


from .abstract import AbstractRegistry
from .elastic_container_registry import ElasticContainerRegistry, EcrConfig
