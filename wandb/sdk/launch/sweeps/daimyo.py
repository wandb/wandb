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
    STARTING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5
    UNKNOWN = 6

class Daimyo(ABC):
    """ Daimyo 🏯  is a Lord in feudal Japan and Boba Fett's title in the Mandalorian.

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
        sweep: Optional[str] = None,
        **kwargs,
    ):
        self._api = api
        self._entity = entity
        self._project = project
        self._queue = queue
        self._sweep = sweep
        self._state: DaimyoState = DaimyoState.STARTING

        _msg = "Daimyo starting."
        logger.debug(_msg)
        wandb.termlog(_msg)

    @property
    def state(self) -> DaimyoState:
        logger.debug(f"Daimyo state: {self._state.name}")
        return self._state

    @abstractmethod
    def _run(self):
        pass
    @abstractmethod
    def _exit(self):
        pass

    def run(self):
        try:
            self._run()
        except KeyboardInterrupt:
            _msg = "Daimyo received KeyboardInterrupt. Exiting."
            logger.debug(_msg)
            wandb.termlog(_msg)
            self._state = DaimyoState.CANCELLED
            self._exit()
            return
        except Exception as e:
            _msg = f"Daimyo failed with exception {e}"
            logger.debug(_msg)
            wandb.termlog(_msg)
            self._state = DaimyoState.FAILED
            raise e

    def _add_to_launch_queue(self, runspec: Dict[str, Any]) -> "public.QueuedJob":
        """ Add a launch job to the Launch RunQueue. """
        return launch_add(
            uri: str,
            config: Optional[Union[str, Dict[str, Any]]] = None,
            project = self._project,
            entity = self._entity,
            queue = self._queue,
            resource = "local-process",
            entry_point: Optional[str] = None,
            name: Optional[str] = None,
            version: Optional[str] = None,
            docker_image: Optional[str] = None,
            params: Optional[Dict[str, Any]] = None,
        )

    def __iter__(self):
        # returning __iter__ object
        return self

    @abstractmethod
    def suggest() -> Dict[str, Any]:
        """ Returns the next suggestion for the sweep. """
        pass

    def __next__(self):
        try:
            return self.next_suggestion()
        except StopIteration:
            raise StopIteration
        except LaunchError as e:
            raise LaunchError(e)
        

