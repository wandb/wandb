import logging

from .local import LocalBackend

__logger__ = logging.getLogger(__name__)


# Statically register backend defined in wandb
WANDB_BACKENDS = {
    "local": LocalBackend,
}


def load_backend(backend_name):
    # Static backends
    if backend_name in WANDB_BACKENDS:
        return WANDB_BACKENDS[backend_name]()

    return None
