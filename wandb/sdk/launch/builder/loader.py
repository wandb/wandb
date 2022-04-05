import logging
from typing import Any, Dict, Type

from wandb.apis.internal import Api
from wandb.errors import LaunchError
from .kaniko import KanikoBuilder

# from .build import DockerBuilder
from .abstract import AbstractBuilder


__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_BUILDERS: Dict[str, Type["AbstractBuilder"]] = {
    # "docker": DockerBuilder,
    "kaniko": KanikoBuilder,
}


def load_builder(builder_name: str, backend_config: Dict[str, Any]) -> AbstractBuilder:
    # Static backends
    if builder_name in WANDB_BUILDERS:
        return WANDB_BUILDERS[builder_name](backend_config)

    raise LaunchError(
        "Builder name not among available builders. Available builders: {} ".format(
            ",".join(list(WANDB_BUILDERS.keys()))
        )
    )
