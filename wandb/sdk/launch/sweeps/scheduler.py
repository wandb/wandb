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


class RunState(Enum):
    QUEUED = 0
    RUNNING = 1
    STOPPED = 2
    ERRORED = 3
    DONE = 4
    UNKNOWN = 5


@dataclass
class SweepRun:
    id: str
    state: str = RunState.QUEUED
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
        # This is internal API
        self._api = api
        # TODO(hupo): Verify that the launch queue exists or create it?
        self._launch_queue = queue

        self._entity = (
            entity
            or os.environ.get("WANDB_ENTITY")
            or api.settings("entity")
            or api.default_entity
        )
        if self._entity is None:
            raise SweepError("Sweep Daimyo could not resolve entity.")

        self._project = (
            project or os.environ.get("WANDB_PROJECT") or api.settings("project")
        )
        if self._project is None:
            raise SweepError("Sweep Daimyo could not resolve project.")

        self._state: SchedulerState = SchedulerState.PENDING
        self._runs: Dict[str, SweepRun] = {}

    @abstractmethod
    def _start(self):
        pass

    @abstractmethod
    def _run(self):
        pass

    @abstractmethod
    def _exit(self):
        pass

    @property
    def state(self) -> SchedulerState:
        logger.debug(f"Daimyo state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: SchedulerState) -> None:
        logger.debug(f"Changing Daimyo state from {self.state.name} to {value.name}")
        self._state = value

    def start(self):
        _msg = "Daimyo starting."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._state = SchedulerState.STARTING
        self._start()
        # TODO(hupo): Should start call run?
        self.run()

    def is_alive(self) -> bool:
        if self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.FAILED,
            SchedulerState.CANCELLED,
        ]:
            return False
        return True

    def run(self):
        _msg = "Daimyo Running."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self.state = SchedulerState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                self.update_run_states()
                self._run()
        except KeyboardInterrupt:
            _msg = "Daimyo received KeyboardInterrupt. Exiting."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.CANCELLED
            self.exit()
            return
        except Exception as e:
            _msg = f"Daimyo failed with exception {e}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.FAILED
            self.exit()
            raise e
        else:
            _msg = f"Daimyo completed."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = SchedulerState.COMPLETED
            self.exit()

    def _add_to_launch_queue(self, launch_spec: Dict[str, Any]):
        """Add a launch job to the Launch RunQueue."""
        run_id: str = launch_spec.get("run_id", generate_id())
        job = launch_add(
            launch_spec.get("uri", None),
            launch_spec.get("config", None),
            project=launch_spec.get("project", None) or self._project,
            entity=launch_spec.get("entity", None) or self._entity,
            queue=launch_spec.get("queue", None) or self._launch_queue,
            resource=launch_spec.get("resource", None),
            entry_point=launch_spec.get("entry_point", None),
            run_id=run_id,
            # name: Optional[str] = None,
            # version: Optional[str] = None,
            # docker_image: Optional[str] = None,
            # params: Optional[Dict[str, Any]] = None,
        )
        self._runs[run_id].launch_job = job
        _msg = f"Added job to Launch RunQueue (RunID:{run_id})."
        logger.debug(_msg)
        wandb.termlog(_msg)

    def update_run_states(self):
        for run_id, run in self._runs.items():
            try:
                _state = self._api.get_run_state(self._entity, self._project, run_id)
            except Exception as e:
                breakpoint()
                pass
            if _state == "running":
                run.state = RunState.RUNNING
            elif _state == "error":
                run.state = RunState.ERRORED
            elif _state == "done":
                run.state = RunState.DONE
            else:
                run.state = RunState.UNKNOWN

    def _stop_run(self, run_id):
        _msg = f"Stopping run {run_id}."
        logger.debug(_msg)
        wandb.termlog(_msg)
        run = self._runs.get(run_id, None)
        if run is not None:
            # TODO(hupo): Can you upsert a run state?
            run.state = RunState.STOPPED

    def exit(self):
        for run_id in self._runs.keys():
            self._stop_run(run_id)
        self._exit()

    # def __iter__(self):
    #     # returning __iter__ object
    #     return self

    # @abstractmethod
    # def suggest() -> Dict[str, Any]:
    #     """ Returns the next suggestion for the sweep. """
    #     pass

    # def __next__(self):
    #     try:
    #         return self.next_suggestion()
    #     except LaunchError as e:
    #         raise StopIteration
