import os
import pathlib

os.environ["_WANDB_CORE_PATH"] = str(pathlib.Path(__file__).parent.absolute())

from .wandb_core import *  # noqa: F403

__doc__ = wandb_core.__doc__  # noqa: F405
if hasattr(wandb_core, "__all__"):  # noqa: F405
    __all__ = wandb_core.__all__  # noqa: F405

__all__.extend(
    (
        "get_core_path",
        "get_nexus_path",
    )
)


def get_core_path() -> pathlib.Path:
    return (pathlib.Path(__file__).parent / "wandb-core").resolve()


# for backwards compatibility
def get_nexus_path() -> pathlib.Path:
    return get_core_path()
