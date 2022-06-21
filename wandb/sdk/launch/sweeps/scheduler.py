from dataclasses import dataclass
import os
from abc import ABC, abstractmethod
from enum import Enum
import logging
from typing import Any, Dict, List, Optional

import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.errors import SweepError
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
    state: str = SimpleRunState.ALIVE
    launch_job: public.QueuedJob = None
    args: Dict[str, Any] = None
    logs: List[str] = None
    program: str = None


class Scheduler(ABC):
    """The Scheduler is a controller/agent that will populate a Launch RunQueue
    with jobs from a hyperparameter sweep.
    """

    def __init__(
        self,
        api: Api,
        *args,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        queue: Optional[str] = None,
        **kwargs,
    ):
        self._api = api
        self._launch_queue = queue
        self._entity = (
            entity
            or os.environ.get("WANDB_ENTITY")
            or api.settings("entity")
            or api.default_entity
        )
        if self._entity is None:
            raise SweepError("Sweep Scheduler could not resolve entity.")

        self._project = (
            project or os.environ.get("WANDB_PROJECT") or api.settings("project")
        )
        if self._project is None:
            raise SweepError("Sweep Scheduler could not resolve project.")

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
        # TODO(hupo): Should start call run?
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
            _msg = f"Scheduler completed."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.COMPLETED
            self.exit()

    def exit(self) -> None:
        if not self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.CANCELLED,
        ]:
            self.state = SchedulerState.FAILED
        for run_id in self._runs.keys():
            self._stop_run(run_id)
        self._exit()

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

    def _add_to_launch_queue(
        self,
        uri: str = None,
        resource: str = None,
        entry_point: List[str] = None,
        run_id: str = None,
    ) -> "public.QueuedJob":
        """Add a launch job to the Launch RunQueue."""
        run_id = run_id or generate_id()
        job = launch_add(
            uri,
            project=self._project,
            entity=self._entity,
            queue=self._launch_queue,
            resource=resource,
            entry_point=entry_point,
            run_id=run_id,
            # config: Optional[Union[str, Dict[str, Any]]] = None,
            # name: Optional[str] = None,
            # version: Optional[str] = None,
            # docker_image: Optional[str] = None,
            # params: Optional[Dict[str, Any]] = None,
        )
        self._runs[run_id].launch_job = job
        _msg = f"Added job to Launch RunQueue: {self._launch_queue} RunID:{run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        return job

    def _stop_run(self, run_id) -> None:
        _msg = f"Stopping run {run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        run = self._runs.get(run_id, None)
        if run is not None:
            run.state = SimpleRunState.DEAD
