"""W&B SDK module."""

from typing import TYPE_CHECKING

__all__ = (
    "Config",
    "Settings",
    "Summary",
    "Artifact",
    "AlertLevel",
    "init",
    "setup",
    "_attach",
    "_sync",
    "login",
    "require",
    "finish",
    "teardown",
    "_watch",
    "_unwatch",
    "sweep",
    "controller",
    "helper",
)

if TYPE_CHECKING:
    from .artifacts.artifact import Artifact

from . import wandb_helper as helper
from .wandb_alerts import AlertLevel
from .wandb_config import Config
from .wandb_init import _attach, init
from .wandb_login import login
from .wandb_require import require
from .wandb_run import finish
from .wandb_settings import Settings
from .wandb_setup import setup, teardown
from .wandb_summary import Summary
from .wandb_sweep import controller, sweep
from .wandb_watch import _unwatch, _watch


def __getattr__(name: str):
    # Loading the Artifact class pulls in most of the SDK, so it is resolved
    # lazily; see https://docs.python.org/3/reference/datamodel.html#customizing-module-attribute-access
    if name == "Artifact":
        from .artifacts.artifact import Artifact

        globals()[name] = Artifact
        return Artifact
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | {"Artifact"})
