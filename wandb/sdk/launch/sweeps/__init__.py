import logging
from typing import Any, Callable, Dict

log = logging.getLogger(__name__)


class SchedulerError(Exception):
    """Raised when a known error occurs with wandb sweep scheduler."""


def _import_sweep_scheduler() -> Any:
    from .scheduler_sweep import SweepScheduler

    return SweepScheduler


_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "wandb": _import_sweep_scheduler,
}


def load_scheduler(scheduler_type: str) -> Any:
    scheduler_type = scheduler_type.lower()
    if scheduler_type not in _WANDB_SCHEDULERS:
        raise SchedulerError(
            f"The `scheduler_name` argument must be one of "
            f"{list(_WANDB_SCHEDULERS.keys())}, got: {scheduler_type}"
        )

    log.warn(f"Loading dependencies for Scheduler of type: {scheduler_type}")
    import_func = _WANDB_SCHEDULERS[scheduler_type]
    return import_func()


__all__ = [
    "load_scheduler",
]
