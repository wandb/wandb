"""Scheduler for Optuna HPO Library."""
import logging
import os
from typing import Any, Callable, List, Optional

import optuna
import wandb
from wandb.errors import SweepError
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)

logger = logging.getLogger(__name__)

class OptunaScheduler(Scheduler):
    """An OptunaScheduler uses the Optuna library to perform hyperparameter sweeps.

    More information on Optuna can be found at:
        https://optuna.readthedocs.io/en/stable/index.html

    """

    def __init__(
        self,
        *args: Any,
        optimize_func: Optional[Callable[[Any], Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.optimize_func: Callable = optimize_func
        self.study = optuna.create_study(
            sampler=,
            pruner=,
            # storage=TODO(hupo): Artifact based state storage,
        )

    def _start(self) -> None:
        wandb.termlog(f"{LOG_PREFIX}Optuna Sampler is {self.study.sampler.__class__.__name__}")
        wandb.termlog(f"{LOG_PREFIX}Optuna Pruner is {self.study.pruner.__class__.__name__}")
        pass

    def _run(self) -> None:

        _trial = self.study.ask()

        # Potentially upsert run?
        _trial.params # https://optuna.readthedocs.io/en/stable/reference/generated/optuna.trial.Trial.html#optuna.trial.Trial.params
        self._api.upsert_run()

        self.study.tell(_trial)
        entry_point: List[str] = []
        queued_run = self._add_to_launch_queue(entry_point=entry_point)

    def _exit(self) -> None:
        pass