import logging
import os
import pprint
import queue
import socket
import threading
import time
from typing import Any, Optional

import wandb
from wandb.errors import SweepError

from .scheduler import Scheduler, SchedulerState, SimpleRunState, SweepRun

logger = logging.getLogger(__name__)


class Scheduler(Scheduler):
    """A Scheduler is a controller/agent that will populate a Launch RunQueue with
    launch jobs it creates from run suggestions it pulls from an internal sweeps RunQueue.
    """

    def __init__(
        self,
        *args: Any,
        sweep_id: Optional[str] = None,
        heartbeat_thread_sleep: int = 3,
        heartbeat_queue_timeout: int = 3,
        main_thread_sleep: int = 3,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Make sure the provided sweep_id corresponds to a valid sweep
        found = self._api.sweep(
            sweep_id, "{}", entity=self._entity, project=self._project
        )
        if not found:
            raise SweepError(
                f"Could not find sweep {self._entity}/{self._project}/{sweep_id}"
            )
        self._sweep_id = sweep_id


    def _start(self) -> None:
        pass

    def _run(self) -> None:
        _ = self._add_to_launch_queue(
            uri=os.environ.get(wandb.env.DIR, os.getcwd()),
            resource="local-process",
            entry_point=entry_point,
            run_id=run.id,
            params=run.args,
        )

    def _exit(self) -> None:
        self.state = SchedulerState.COMPLETED
