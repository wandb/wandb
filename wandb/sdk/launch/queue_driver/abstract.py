from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

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
    async def pop_from_run_queue(self) -> Optional[Dict[str, Any]]:
        """Determine which item should run next and pop it.

        Returns:
            The job if lease was acquired, otherwise None
        """
        raise NotImplementedError

    @abstractmethod
    async def ack_run_queue_item(self, job_id: str, run_name: str) -> bool:
        """Mark a run queue item as running.

        Arguments:
            job_id: ID of the run queue item to ack
            run_name: ID of the associated run

        Returns:
            Whether the call was successful
        """
        raise NotImplementedError

    @abstractmethod
    async def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: Optional[List[str]] = None,
    ) -> bool:
        """Mark a run queue item as failed.

        Arguments:
            run_queue_item_id: ID of the run queue item that failed
            message: Reason the run failed
            stage: Stage at which the run failed ("agent", "build", "run")
            file_paths: Files (e.g. logs) that can help to debug

        Returns:
            Whether the call was successful
        """
        raise NotImplementedError
