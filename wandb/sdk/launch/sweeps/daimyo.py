from dataclasses import dataclass
import os
from abc import ABC, abstractmethod
from enum import Enum
import logging
from typing import Any, Dict, Optional
import threading

import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.errors import SweepError
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.lib.runid import generate_id


logger = logging.getLogger(__name__)


class DaimyoState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5

class LaunchJobState(Enum):
    QUEUED = 0
    RUNNING = 1
    STOPPED = 2
    ERRORED = 3
    DONE = 4
    UNKNOWN = 5

@dataclass
class LaunchJob:
    job : public.QueuedJob
    state : str = LaunchJobState.QUEUED


class Daimyo(ABC):
    """Daimyo 🏯  is a Lord in feudal Japan and Boba Fett's title in the Mandalorian.

    In this context, the Daimyo is a controller/agent that will populate a Launch RunQueue
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
            project
            or os.environ.get("WANDB_PROJECT")
            or api.settings("project")
        )
        if self._project is None:
            raise SweepError("Sweep Daimyo could not resolve project.")

        self._state: DaimyoState = DaimyoState.PENDING
        self._launch_jobs: Dict[str, LaunchJob] = {}

    @property
    def state(self) -> DaimyoState:
        logger.debug(f"Daimyo state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: DaimyoState) -> None:
        logger.debug(f"Changing Daimyo state from {self.state.name} to {value.name}")
        self._state = value

    @abstractmethod
    def _start(self):
        pass

    def start(self):
        _msg = "Daimyo starting."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._state = DaimyoState.STARTING
        self._start()
        # TODO(hupo): Should start call run?
        self.run()

    @abstractmethod
    def _run(self):
        pass

    @abstractmethod
    def _exit(self):
        pass

    def is_alive(self) -> bool:
        if self.state in [
            DaimyoState.COMPLETED,
            DaimyoState.FAILED,
            DaimyoState.CANCELLED,
        ]:
            return False
        return True

    def run(self):
        _msg = "Daimyo Running."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self.state = DaimyoState.RUNNING
        try:
            while True:
                if not self.is_alive():
                    break
                self.update_launch_jobs()
                self._run()
        except KeyboardInterrupt:
            _msg = "Daimyo received KeyboardInterrupt. Exiting."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = DaimyoState.CANCELLED
            self._exit()
            return
        except Exception as e:
            _msg = f"Daimyo failed with exception {e}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = DaimyoState.FAILED
            self._exit()
            raise e
        else:
            _msg = f"Daimyo completed."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self.state = DaimyoState.COMPLETED
            self._exit()

    def _add_to_launch_queue(self, launch_spec: Dict[str, Any]) -> "public.QueuedJob":
        """Add a launch job to the Launch RunQueue."""
        run_id: str = launch_spec.get('run_id', generate_id()) 
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
        _msg = f"Added job to Launch RunQueue (RunID:{run_id})."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self._launch_jobs[run_id] = LaunchJob(job)
        return job

    def update_launch_jobs(self):
        for job_id, job in self._launch_jobs.items():
            try:
                _state = self._api.get_run_state(self._entity, self._project, job_id)
            except Exception as e:
                breakpoint()
                pass
            if _state == "running":
                job.state = LaunchJobState.RUNNING
            elif _state == "error":
                job.state = LaunchJobState.ERRORED
            elif _state == "done":
                job.state = LaunchJobState.DONE
            else:
                job.state = LaunchJobState.UNKNOWN


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
