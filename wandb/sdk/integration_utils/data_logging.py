# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.
import wandb

if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING, Callable, Any

    if TYPE_CHECKING:
        import numpy as np


class _TensorColumnDef(object):
    _name: str
    _tensor: "np.ndarray"
    _transformation_fn: Callable[["np.ndarray"], Any]


def _make_table_from_tensors():
    pass
