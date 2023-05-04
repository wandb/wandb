import logging
from typing import Any, Callable, Dict

log = logging.getLogger(__name__)


class SchedulerError(Exception):
    """Raised when a known error occurs with wandb sweep scheduler."""

    pass


def _import_sweep_scheduler() -> Any:
    from .scheduler_sweep import SweepScheduler

    return SweepScheduler


def _import_optuna_scheduler() -> Any:
    from .scheduler_optuna import OptunaScheduler

    return OptunaScheduler


_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "sweep": _import_sweep_scheduler,
    "optuna": _import_optuna_scheduler,
}


def load_scheduler(scheduler_type: str) -> Any:
    scheduler_type = scheduler_type.lower()
    if scheduler_type not in _WANDB_SCHEDULERS:
        raise SchedulerError(
            f"The `scheduler_type` argument must be one of "
            f"{list(_WANDB_SCHEDULERS.keys())}, got: {scheduler_type}"
        )

    log.warn(f"Loading dependencies for Scheduler of type: {scheduler_type}")
    import_func = _WANDB_SCHEDULERS[scheduler_type]
    return import_func()


__all__ = [
    "load_scheduler",
]
