import logging
from typing import Any, Dict, Type

from wandb.apis.internal import Api
from wandb.errors import LaunchError

from .abstract import AbstractRunner
from .aws import AWSSagemakerRunner
from .gcp_vertex import VertexRunner
from .kubernetes import KubernetesRunner
from .local import LocalRunner


__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_RUNNERS: Dict[str, Type["AbstractRunner"]] = {
    "local": LocalRunner,
    "gcp-vertex": VertexRunner,
    "sagemaker": AWSSagemakerRunner,
    "kubernetes": KubernetesRunner,
}


def load_backend(
    backend_name: str, api: Api, backend_config: Dict[str, Any]
) -> AbstractRunner:
    # Static backends
    if backend_name in WANDB_RUNNERS:
        return WANDB_RUNNERS[backend_name](api, backend_config)

    raise LaunchError(
        "Resource name not among available resources. Available resources: {} ".format(
            ",".join(list(WANDB_RUNNERS.keys()))
        )
    )
