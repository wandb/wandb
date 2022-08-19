import logging
from typing import Any, Callable, Dict

log = logging.getLogger(__name__)


class SchedulerError(Exception):
    """Raised when a known error occurs with wandb sweep scheduler"""

    pass


def _import_sweep_scheduler() -> Any:
    from .scheduler_sweep import SweepScheduler

    return SweepScheduler

def _import_optuna_scheduler() -> Any:
    from .scheduler_optuna import OptunaScheduler

    return OptunaScheduler


_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "sweep": _import_sweep_scheduler,
    "classic": _import_sweep_scheduler,
    "optuna": _import_optuna_scheduler,
}


def load_scheduler(scheduler_name: str) -> Any:

    scheduler_name = scheduler_name.lower()
    if scheduler_name not in _WANDB_SCHEDULERS:
        raise SchedulerError(
            f"The `scheduler_name` argument must be one of "
            f"{list(_WANDB_SCHEDULERS.keys())}, got: {scheduler_name}"
        )

    log.warn(f"Loading dependencies for Scheduler of type: {scheduler_name}")
    import_func = _WANDB_SCHEDULERS[scheduler_name]
    return import_func()


__all__ = [
    "load_scheduler",
]
