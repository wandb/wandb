"""Scheduler for Optuna HPO Library."""
import logging
import os
from typing import Any, Optional

import optuna
import wandb
from wandb.errors import SweepError

from .scheduler import Scheduler, SchedulerState, SimpleRunState, SweepRun

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

    def _start(self) -> None:
        pass

    def _run(self) -> None:
        pass

    def _exit(self) -> None:
        pass