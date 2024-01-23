from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.agent2.job_set import JobSet


class AbstractQueueDriver(ABC):
    """Abstract plugin class defining the interface needed to implement a Launch Queue Driver."""

    api: Api
    job_set: JobSet

    @abstractmethod
    def __init__(self, api: Api, job_set: JobSet) -> None:
        """Initialize a queue driver.

        Arguments:
            api: Internal API, this should eventually not be required
            job_set: The job set to use
        """
        raise NotImplementedError

    @abstractmethod
    def pop_from_run_queue(self) -> Optional[Dict[str, Any]]:
        """Determine which item should run next and pop it.

        Returns:
            The job if lease was acquired, otherwise None
        """
        raise NotImplementedError

    @abstractmethod
    def ack_run_queue_item(self, job_id: str, run_name: str) -> bool:
        """Mark a run queue item as running.

        Arguments:
            job_id: ID of the run queue item to ack

        Returns:
            Whether the call was successful
        """
        raise NotImplementedError

    @abstractmethod
    def fail_run_queue_item(self, job_id: str, run_name: str) -> bool:
        """Mark a run queue item as failed.

        Arguments:
            job_id: The ID of the run queue item that failed

        Returns:
            Whether the call was successful
        """
        raise NotImplementedError
