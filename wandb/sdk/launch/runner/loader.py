import logging
from typing import Any, Dict, List

from wandb.apis.internal import Api
from wandb.errors import LaunchError

from .abstract import AbstractRunner


__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_RUNNERS: List[str] = [
    "local",
    "local-container",
    "bare",
    "local-process",
    "gcp-vertex",
    "sagemaker",
    "kubernetes",
]


def load_backend(
    backend_name: str, api: Api, backend_config: Dict[str, Any]
) -> AbstractRunner:
    # Static backends
    if backend_name in ["local", "local-container"]:
        from .local_container import LocalContainerRunner

        return LocalContainerRunner(api, backend_config)
    elif backend_name in ["bare", "local-process"]:
        from .local_process import LocalProcessRunner

        return LocalProcessRunner(api, backend_config)
    elif backend_name == "gcp-vertex":
        from .gcp_vertex import VertexRunner

        return VertexRunner(api, backend_config)
    elif backend_name == "sagemaker":
        from .aws import AWSSagemakerRunner

        return AWSSagemakerRunner(api, backend_config)
    elif backend_name == "kubernetes":
        from .kubernetes import KubernetesRunner

        return KubernetesRunner(api, backend_config)
    raise LaunchError(
        "Resource name not among available resources. Available resources: {} ".format(
            ",".join(WANDB_RUNNERS)
        )
    )
