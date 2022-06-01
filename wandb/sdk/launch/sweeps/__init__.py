import logging
from typing import Callable, Dict

from .scheduler import Scheduler


log = logging.getLogger(__name__)


def _import_sweep_scheduler() -> Scheduler:
    from .scheduler_sweep import SweepScheduler

    # TODO: Load dependencies for SweepScheduler
    # pip install wandb[sweeps]
    return SweepScheduler


def _import_tune_scheduler() -> Scheduler:
    from .scheduler_tune import TuneScheduler

    # TODO: Load dependencies for TuneScheduler
    # pip install ray[tune]
    return TuneScheduler


_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "tune": _import_tune_scheduler,
    "sweep": _import_sweep_scheduler,
}


def load_scheduler(scheduler_name: str, *args, **kwargs) -> Scheduler:

    scheduler_name = scheduler_name.lower()
    if scheduler_name not in _WANDB_SCHEDULERS:
        raise ValueError(
            f"The `scheduler_name` argument must be one of "
            f"{list(_WANDB_SCHEDULERS.keys())}, got: {scheduler_name}"
        )

    log.warn(f"Loading dependencies for Daimyo of type: {scheduler_name}")
    import_func = _WANDB_SCHEDULERS[scheduler_name]
    return import_func()(*args, **kwargs)


__all__ = [
    "load_scheduler",
]
