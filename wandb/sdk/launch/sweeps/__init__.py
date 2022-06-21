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

    # NOTE: The Ray Tune scheduler will not be included with this PR,
    # I kept it here so that reviewers would better
    # understand the future context and resulting design choices

    # TODO: Load dependencies for TuneScheduler
    # pip install ray[tune]
    return TuneScheduler


_WANDB_SCHEDULERS: Dict[str, Callable] = {
    "tune": _import_tune_scheduler,
    "sweep": _import_sweep_scheduler,
}


def load_scheduler(scheduler_name: str) -> Scheduler:

    scheduler_name = scheduler_name.lower()
    if scheduler_name not in _WANDB_SCHEDULERS:
        raise ValueError(
            f"The `scheduler_name` argument must be one of "
            f"{list(_WANDB_SCHEDULERS.keys())}, got: {scheduler_name}"
        )

    log.warn(f"Loading dependencies for Scheduler of type: {scheduler_name}")
    import_func = _WANDB_SCHEDULERS[scheduler_name]
    return import_func()


__all__ = [
    "load_scheduler",
]
