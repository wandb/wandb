import logging

from .local import LocalRunner

__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_RUNNERS = {"local": LocalRunner}


def load_backend(backend_name, api=None):
    # Static backends
    if backend_name in WANDB_RUNNERS:
        return WANDB_RUNNERS[backend_name](api)

    raise Exception(
        "Resource name not among available resources. Available resources: {} ".format(
            ",".join(list(WANDB_RUNNERS.keys()))
        )
    )
