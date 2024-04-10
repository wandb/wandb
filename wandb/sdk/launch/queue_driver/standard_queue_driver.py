import logging
from typing import List, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.agent2.jobset import JobSet
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import PRIORITIZATION_MODE

from ..agent2.jobset import Job
from .abstract import AbstractQueueDriver


class StandardQueueDriver(AbstractQueueDriver):
    def __init__(self, api: Api, jobset: JobSet, logger: logging.Logger):
        self.api = api
        self.jobset = jobset
        self.logger = logger

    async def pop_from_run_queue(self) -> Optional[Job]:
        self.logger.debug("Calling pop_from_run_queue")
        if len(self.jobset.jobs) == 0:
            return None
        # get highest prio job
        if self.jobset.metadata.get(PRIORITIZATION_MODE) == "V0":
            job_id, job = sorted(
                self.jobset.jobs.items(), key=lambda j: (j[1].priority, j[1].created_at)
            )[0]
        else:
            job_id, job = sorted(self.jobset.jobs.items(), key=lambda j: j[1].created_at)[0]

        # attempt to acquire lease
        self.logger.debug(f"Attempting to lease job {job_id}")
        lease_result = await self.jobset.lease_job(job_id)
        if not lease_result:
            msg = f"Error leasing job {job_id}"
            self.logger.error(msg)
            raise LaunchError(msg)

        # confirm the item was removed from the job set
        await self.jobset.wait_for_update()
        if job_id in self.jobset.jobs:
            self.logger.warn("Job was not removed from job set")
            return None

        # if lease successful, return job from jobset
        self.logger.debug(f"Successfully leased {job_id}")
        return job

    async def ack_run_queue_item(self, item_id: str, run_id: str):
        return await self.jobset.ack_job(item_id, run_id)

    async def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: Optional[List[str]] = None,
    ):
        return await self.jobset.fail_job(run_queue_item_id, message, stage, file_paths)
