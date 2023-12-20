import os
import pathlib

os.environ["_WANDB_CORE_PATH"] = str(pathlib.Path(__file__).parent.absolute())

from .wandb import *  # noqa: F403

__doc__ = wandb.__doc__  # noqa: F405
if hasattr(wandb, "__all__"):  # noqa: F405
    __all__ = wandb.__all__  # noqa: F405
