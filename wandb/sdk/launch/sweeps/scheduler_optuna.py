"""Scheduler for Optuna HPO Library."""
import logging
import os
from typing import Any, Optional

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
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.study = optuna.create_study(
            sampler=,
            pruner=,
        )

    def _start(self) -> None:
        wandb.termlog(f"{LOG_PREFIX}Optuna Scheduler created")
        wandb.termlog(f"{LOG_PREFIX}Sampler is {self.study.sampler.__class__.__name__}")
        pass

    def _run(self) -> None:
        pass

    def _exit(self) -> None:
        pass