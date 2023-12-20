import os
import pathlib

os.environ["_WANDB_CORE_PATH"] = str(pathlib.Path(__file__).parent.absolute())

from .wandb import *

__doc__ = wandb.__doc__
if hasattr(wandb, "__all__"):
    __all__ = wandb.__all__
