from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
import os
from typing import Any, Dict, List, Optional

import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.lib.runid import generate_id

logger = logging.getLogger(__name__)


class SchedulerState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5


class SimpleRunState(Enum):
    ALIVE = 0
    DEAD = 1
    UNKNOWN = 3


@dataclass
class SweepRun:
    id: str
    state: SimpleRunState = SimpleRunState.ALIVE
    launch_job: Optional[public.QueuedRun] = None
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
        queue: Optional[str] = None,
        **kwargs: Any,
    ):
        self._api = api
        self._launch_queue = queue
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
        logger.debug(f"Scheduler state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: SchedulerState) -> None:
        logger.debug(f"Changing Scheduler state from {self.state.name} to {value.name}")
        self._state = value

    def is_alive(self) -> bool:
        if self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.FAILED,
            SchedulerState.CANCELLED,
        ]:
            return False
        return True

    def start(self) -> None:
        _msg = "Scheduler starting."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._state = SchedulerState.STARTING
        self._start()
        self.run()

    def run(self) -> None:
        _msg = "Scheduler Running."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self.state = SchedulerState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                self._update_run_states()
                self._run()
        except KeyboardInterrupt:
            _msg = "Scheduler received KeyboardInterrupt. Exiting."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.CANCELLED
            self.exit()
            return
        except Exception as e:
            _msg = f"Scheduler failed with exception {e}"
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
            SchedulerState.CANCELLED,
        ]:
            self.state = SchedulerState.FAILED
        for run_id in self._runs.keys():
            self._stop_run(run_id)

    def _update_run_states(self) -> None:
        for run_id, run in self._runs.items():
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
                _msg = f"Issue when getting RunState for Run {run_id}: {e}"
                logger.debug(_msg)
                wandb.termlog(_msg)
                run.state = SimpleRunState.UNKNOWN
                continue

    def _add_to_launch_queue(
        self,
        uri: Optional[str] = None,
        resource: Optional[str] = None,
        entry_point: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> "public.QueuedRun":
        """Add a launch job to the Launch RunQueue."""
        run_id = run_id or generate_id()
        job = launch_add(
            uri or os.environ.get(wandb.env.DIR, os.getcwd()) or "",
            project=self._project,
            entity=self._entity,
            queue=self._launch_queue,
            resource=resource,
            entry_point=entry_point,
            # params=params,
            run_id=run_id,
        )
        self._runs[run_id].launch_job = job
        _msg = f"Added job to Launch RunQueue: {self._launch_queue} RunID:{run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        return job

    def _stop_run(self, run_id: str) -> None:
        _msg = f"Stopping run {run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        run = self._runs.get(run_id, None)
        if run is not None:
            run.state = SimpleRunState.DEAD
