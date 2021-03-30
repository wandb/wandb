import logging

from .local import LocalBackend
from .ngc import NGCBackend

__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_BACKENDS = {"local": LocalBackend, "ngc": NGCBackend}


def load_backend(backend_name, api_key=None):
    # Static backends
    if backend_name in WANDB_BACKENDS:
        return WANDB_BACKENDS[backend_name](api_key)

    return None
