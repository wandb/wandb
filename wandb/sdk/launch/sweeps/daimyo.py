from abc import ABC, abstractmethod
from enum import Enum
import logging
from typing import Any, Dict, Optional

import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.errors import LaunchError
from wandb.sdk.launch.launch_add import launch_add


logger = logging.getLogger(__name__)


class DaimyoState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5


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
        # TODO: verify these properties, throw errors
        self._api = api
        self._entity = entity
        self._project = project
        self._queue = queue
        self._state: DaimyoState = DaimyoState.PENDING
        self._jobs: Dict[str, public.QueuedJob] = {}

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
        # TODO: Should start call run?
        self.run()

    @abstractmethod
    def _run(self):
        pass

    @abstractmethod
    def _exit(self):
        pass

    def run(self):
        _msg = "Daimyo Running."
        logger.debug(_msg)
        wandb.termlog(_msg)
        self.state = DaimyoState.RUNNING
        try:

            # check status of jobs (runs) through graphql
            # change status of jobs (runs) through graphql

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

    def _add_to_launch_queue(self, launchspec: Dict[str, Any]) -> "public.QueuedJob":
        """Add a launch job to the Launch RunQueue."""
        job = launch_add(
            launchspec.get("uri", None),
            launchspec.get("config", None),
            project=launchspec.get("project", None) or self._project,
            entity=launchspec.get("entity", None) or self._entity,
            queue=launchspec.get("queue", None) or self._queue,
            resource="local-process",
            # entry_point: Optional[str] = None,
            # name: Optional[str] = None,
            # version: Optional[str] = None,
            # docker_image: Optional[str] = None,
            # params: Optional[Dict[str, Any]] = None,
        )
        self._jobs[job._run_id] = job
        return job

    def is_alive(self) -> bool:
        if self.state in [
            DaimyoState.COMPLETED,
            DaimyoState.FAILED,
            DaimyoState.CANCELLED,
        ]:
            return False
        return True

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
