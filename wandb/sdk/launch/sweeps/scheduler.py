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
    UNKNOWN = 3


@dataclass
class SweepRun:
    id: str
    state: SimpleRunState = SimpleRunState.ALIVE
    queued_run: Optional[public.QueuedRun] = None
    args: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    program: Optional[str] = None


class Scheduler(ABC):
    """The Scheduler is a controller/agent that will populate a Launch RunQueue
    with jobs from a hyperparameter sweep.
    """

    def __init__(
        self,
        api: Api,
        *args: Any,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        # ------- Begin Launch Options -------
        queue: Optional[str] = None,
        job: Optional[str] = None,
        resource: Optional[str] = None,
        resource_args: Optional[Dict[str, Any]] = None,
        # ------- End Launch Options -------
        **kwargs: Any,
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
        # ------- Begin Launch Options -------
        # TODO(hupo): Validation on these arguments.
        self._launch_queue = queue
        self._job = job
        self._resource = resource
        self._resource_args = resource_args
        if resource == "kubernetes":
            self._resource_args = {"kubernetes": {}}
        # ------- End Launch Options -------
        self._state: SchedulerState = SchedulerState.PENDING
        self._threading_lock: threading.Lock = threading.Lock()
        self._runs: Dict[str, SweepRun] = {}

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
        logger.debug(
            f"{LOG_PREFIX}Changing Scheduler state from {self.state.name} to {value.name}"
        )
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
        _msg = f"{LOG_PREFIX}Scheduler starting."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._state = SchedulerState.STARTING
        self._start()
        self.run()

    def run(self) -> None:
        _msg = f"{LOG_PREFIX}Scheduler Running."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self.state = SchedulerState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                try:
                    self._update_run_states()
                    self._run()
                except RuntimeError as e:
                    _msg = f"{LOG_PREFIX}Scheduler encountered Runtime Error. {e} Trying again."
                    logger.debug(_msg)
                    wandb.termlog(_msg)
        except KeyboardInterrupt:
            _msg = f"{LOG_PREFIX}Scheduler received KeyboardInterrupt. Exiting."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.STOPPED
            self.exit()
            return
        except Exception as e:
            _msg = f"{LOG_PREFIX}Scheduler failed with exception {e}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.FAILED
            self.exit()
            raise e
        else:
            _msg = "Scheduler completed."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.exit()

    def exit(self) -> None:
        self._exit()
        if self.state not in [
            SchedulerState.COMPLETED,
            SchedulerState.STOPPED,
        ]:
            self.state = SchedulerState.FAILED
        for run_id, _ in self._yield_runs():
            self._stop_run(run_id)

    def _yield_runs(self) -> Iterator[Tuple[str, SweepRun]]:
        """Thread-safe way to iterate over the runs."""
        with self._threading_lock:
            yield from self._runs.items()

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

    def _add_to_launch_queue(
        self,
        entry_point: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> "public.QueuedRun":
        """Add a launch job to the Launch RunQueue."""
        run_id = run_id or generate_id()
        queued_run = launch_add(
            # TODO(hupo): If no Job is specified, use a placeholder URI to prevent Launch failure
            uri=None if self._job is not None else "placeholder-uri-queuedrun",
            job=self._job,
            project=self._project,
            entity=self._entity,
            queue=self._launch_queue,
            entry_point=entry_point,
            resource=self._resource,
            resource_args=self._resource_args,
            run_id=run_id,
        )
        self._runs[run_id].queued_run = queued_run
        _msg = f"{LOG_PREFIX}Added run to Launch RunQueue: {self._launch_queue} RunID:{run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        return queued_run

    def _stop_run(self, run_id: str) -> None:
        _msg = f"{LOG_PREFIX}Stopping run {run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        run = self._runs.get(run_id, None)
        if run is not None:
            run.state = SimpleRunState.DEAD
