"""Abstract Scheduler class."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
import os
import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

import click
import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.lib.runid import generate_id

logger = logging.getLogger(__name__)
LOG_PREFIX = f"{click.style('sched:', fg='cyan')}: "


class SchedulerState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    STOPPED = 5


class SimpleRunState(Enum):
    ALIVE = 0
    DEAD = 1
    UNKNOWN = 2


@dataclass
class SweepRun:
    id: str
    state: SimpleRunState = SimpleRunState.ALIVE
    queued_run: Optional[public.QueuedRun] = None
    args: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    program: Optional[str] = None
    # Threading can be used to run multiple workers in parallel
    worker_id: Optional[int] = None
    worker_thread: Optional[threading.Thread] = None


class Scheduler(ABC):
    """The Scheduler is a controller/agent that will populate a Launch RunQueue
    with jobs from a hyperparameter sweep.
    """

    def __init__(
        self,
        api: Api,
        *args: Optional[Any],
        entity: Optional[str] = None,
        project: Optional[str] = None,
        **kwargs: Optional[Any],
    ):
        self._api = api
        self._entity = (
            entity
            or os.environ.get("WANDB_ENTITY")
            or api.settings("entity")
            or api.default_entity
        )
        self._project = (
            project or os.environ.get("WANDB_PROJECT") or api.settings("project")
        )
        self._state: SchedulerState = SchedulerState.PENDING
        self._threading_lock: threading.Lock = threading.Lock()
        # List of the runs managed by the scheduler
        self._runs: Dict[str, SweepRun] = {}
        self._kwargs: Dict[str, Any] = kwargs

    @abstractmethod
    def _start(self) -> None:
        pass

    @abstractmethod
    def _run(self) -> None:
        pass

    @abstractmethod
    def _exit(self) -> None:
        pass

    @property
    def state(self) -> SchedulerState:
        logger.debug(f"{LOG_PREFIX}Scheduler state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: SchedulerState) -> None:
        logger.debug(f"{LOG_PREFIX}Scheduler was {self.state.name} is {value.name}")
        self._state = value

    def is_alive(self) -> bool:
        if self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.FAILED,
            SchedulerState.STOPPED,
        ]:
            return False
        return True

    def start(self) -> None:
        wandb.termlog(f"{LOG_PREFIX}Scheduler starting.")
        self._state = SchedulerState.STARTING
        self._start()
        self.run()

    def run(self) -> None:
        wandb.termlog(f"{LOG_PREFIX}Scheduler Running.")
        self.state = SchedulerState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                try:
                    self._update_run_states()
                    self._run()
                except RuntimeError as e:
                    wandb.termlog(
                        f"{LOG_PREFIX}Scheduler encountered Runtime Error. {e} Trying again."
                    )
        except KeyboardInterrupt:
            wandb.termlog(f"{LOG_PREFIX}Scheduler received KeyboardInterrupt. Exiting.")
            self.state = SchedulerState.STOPPED
            self.exit()
            return
        except Exception as e:
            wandb.termlog(f"{LOG_PREFIX}Scheduler failed with exception {e}")
            self.state = SchedulerState.FAILED
            self.exit()
            raise e
        else:
            wandb.termlog(f"{LOG_PREFIX}Scheduler completed.")
            self.exit()

    def exit(self) -> None:
        self._exit()
        if self.state not in [
            SchedulerState.COMPLETED,
            SchedulerState.STOPPED,
        ]:
            self.state = SchedulerState.FAILED
        self._stop_runs()

    def _yield_runs(self) -> Iterator[Tuple[str, SweepRun]]:
        """Thread-safe way to iterate over the runs."""
        with self._threading_lock:
            yield from self._runs.items()

    def _stop_runs(self) -> None:
        for run_id, _ in self._yield_runs():
            wandb.termlog(f"{LOG_PREFIX}Stopping run {run_id}.")
            self._stop_run(run_id)

    @abstractmethod
    def _stop_run(self, run_id: str) -> None:
        pass

    def _update_run_states(self) -> None:
        for run_id, run in self._yield_runs():
            try:
                _state = self._api.get_run_state(self._entity, self._project, run_id)
                if _state is None or _state in [
                    "crashed",
                    "failed",
                    "killed",
                    "finished",
                ]:
                    run.state = SimpleRunState.DEAD
                elif _state in [
                    "running",
                    "pending",
                    "preempted",
                    "preempting",
                ]:
                    run.state = SimpleRunState.ALIVE
            except Exception as e:
                _msg = f"{LOG_PREFIX}Issue when getting RunState for Run {run_id}: {e}"
                logger.debug(_msg)
                wandb.termlog(_msg)
                run.state = SimpleRunState.UNKNOWN
                continue
        # Remove any runs that are dead
        with self._threading_lock:
            for run_id, run in self._runs.items():
                if run.state == SimpleRunState.DEAD:
                    wandb.termlog(f"{LOG_PREFIX}Removing dead run {run_id}.")
                    del self._runs[run_id]

    def _add_to_launch_queue(
        self,
        entry_point: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> "public.QueuedRun":
        """Add a launch job to the Launch RunQueue."""
        run_id = run_id or generate_id()
        # One of Job and URI is required
        _job = self._kwargs.get("job", None)
        _uri = self._kwargs.get("uri", None)
        if _job is None and _uri is None:
            # If no Job is specified, use a placeholder URI to prevent Launch failure
            _uri = "placeholder-uri-queuedrun-from-scheduler"
        queued_run = launch_add(
            run_id=run_id,
            entry_point=entry_point,
            uri=_uri,
            job=_job,
            project=self._project,
            entity=self._entity,
            queue=self._kwargs.get("queue", None),
            resource=self._kwargs.get("resource", None),
            resource_args=self._kwargs.get("resource_args", None),
        )
        self._runs[run_id].queued_run: public.QueuedRun = queued_run
        wandb.termlog(
            f"{LOG_PREFIX}Added run to Launch RunQueue: {self._launch_queue} RunID:{run_id}."
        )
        return queued_run
