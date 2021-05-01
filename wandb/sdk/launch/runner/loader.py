import logging

from .local import LocalRunner
from .ngc import NGCRunner

__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_RUNNERS = {"local": LocalRunner, "ngc": NGCRunner}


def load_backend(backend_name, api_key=None):
    # Static backends
    if backend_name in WANDB_RUNNERS:
        return WANDB_RUNNERS[backend_name](api_key)

    return None
