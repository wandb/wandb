import os
import pathlib

os.environ["_WANDB_CORE_PATH"] = str(pathlib.Path(__file__).parent.absolute())

from .wandbrs import *  # noqa: F403

__doc__ = wandbrs.__doc__  # noqa: F405
if hasattr(wandbrs, "__all__"):  # noqa: F405
    __all__ = wandbrs.__all__  # noqa: F405

__all__.extend(("get_core_path",))


def get_core_path() -> pathlib.Path:
    return (pathlib.Path(__file__).parent / "wandb-core").resolve()
