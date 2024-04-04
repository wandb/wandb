import logging
from typing import List, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.agent2.jobset import JobSet
from wandb.sdk.launch.utils import PRIORITIZATION_MODE

from ..agent2.jobset import Job
from .abstract import AbstractQueueDriver

logger = logging.getLogger(__name__)


class StandardQueueDriver(AbstractQueueDriver):
    def __init__(self, api: Api, jobset: JobSet):
        self.api = api
        self.jobset = jobset

    async def pop_from_run_queue(self) -> Optional[Job]:
        # get highest prio job
        if self.jobset.metadata.get(PRIORITIZATION_MODE) == "V0":
            job = sorted(
                self.jobset.jobs, key=lambda j: (j["priority"], j["createdAt"])
            )[0]
        else:
            job = sorted(self.jobset.jobs, key=lambda j: j["createdAt"])[0]

        # attempt to acquire lease
        lease_result = await self.jobset.lease_job(job["id"])
        if not lease_result:
            return None

        # confirm the item was removed from the job set
        await self.jobset.wait_for_update()
        if job in self.jobset.jobs:
            return None

        # if lease successful, return job from jobset
        return self.jobset.jobs[job]

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
