import inspect
import logging
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict

log = logging.getLogger(__name__)


class SchedulerError(Exception):
    """Raised when a known error occurs with wandb sweep scheduler."""

    pass


def _import_wandb_scheduler() -> Any:
    from .schedulers.scheduler_wandb import WandbScheduler

    return WandbScheduler


def _import_optuna_scheduler() -> Any:
    from .schedulers.scheduler_optuna import OptunaScheduler

    return OptunaScheduler


def _import_raytune_scheduler() -> Any:
    raise NotImplementedError("RayTune is not yet supported in wandb sweep")


def _import_hyperopt_scheduler() -> Any:
    raise NotImplementedError("HyperOpt is not yet supported in wandb sweep")


def _import_custom_scheduler(scheduler_type: str) -> Any:
    """Dynamically import custom scheduler from file."""
    # This assumes launch-agent running forked wandb repo with a
    # custom scheduler file in the 'schedulers' directory
    source_path = Path(__file__).resolve()
    source_dir = source_path.parent
    _path = os.path.join(source_dir, f"schedulers/scheduler_{scheduler_type}.py")

    loader = SourceFileLoader(scheduler_type, _path)
    mod = ModuleType(loader.name)
    loader.exec_module(mod)

    class_members = inspect.getmembers(mod, inspect.isclass)
    log.log(
        0, msg=f"Loaded classes from scheduler_{scheduler_type}.py: {class_members}"
    )
    if f"{scheduler_type.capitalize()}Scheduler" not in dict(class_members):
        raise SchedulerError(
            f"Custom scheduler '{scheduler_type}' must contain a class named '{scheduler_type.capitalize()}Scheduler'"
        )

    return getattr(mod, f"{scheduler_type.capitalize()}Scheduler")


# supported schedulers
_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "wandb": _import_wandb_scheduler,
    "optuna": _import_optuna_scheduler,
    "raytune": _import_raytune_scheduler,
    "hyperopt": _import_hyperopt_scheduler,
}


def load_scheduler(scheduler_type: str) -> Any:
    scheduler_type = scheduler_type.lower()
    if scheduler_type in _WANDB_SCHEDULERS:
        log.log(0, msg=f"Loading dependencies for Scheduler of type: {scheduler_type}")
        import_func = _WANDB_SCHEDULERS[scheduler_type]
        return import_func()

    log.log(0, msg=f"loading custom scheduler: {scheduler_type}")
    # Try dynamically loading custom scheduler
    try:
        import_func = _import_custom_scheduler
        return import_func(scheduler_type)
    except Exception as e:
        raise SchedulerError(
            f"Error loading custom scheduler '{scheduler_type}': {e}"
        ) from e


__all__ = [
    "load_scheduler",
]
