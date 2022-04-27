import logging
from typing import Any, Dict, Type

from wandb.errors import LaunchError

from .abstract import AbstractBuilder
from .docker import DockerBuilder
from .kaniko import KanikoBuilder

__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_BUILDERS: Dict[str, Type["AbstractBuilder"]] = {
    "docker": DockerBuilder,
    "kaniko": KanikoBuilder,
}


def load_builder(builder_config: Dict[str, Any]) -> AbstractBuilder:
    builder_name = builder_config.get("type", "docker")
    if builder_name in WANDB_BUILDERS:
        return WANDB_BUILDERS[builder_name](builder_config)

    raise LaunchError(
        "Builder name not among available builders. Available builders: {} ".format(
            ",".join(list(WANDB_BUILDERS.keys()))
        )
    )
