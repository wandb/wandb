import logging
from typing import Any, Awaitable, Dict, List, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.agent2.job_set import JobSet
from wandb.sdk.launch.utils import PRIORITIZATION_MODE

from .abstract import AbstractQueueDriver

logger = logging.getLogger(__name__)


class StandardQueueDriver(AbstractQueueDriver):
    def __init__(self, api: Api, job_set: JobSet):
        self.api = api
        self.job_set = job_set

    async def pop_from_run_queue(self) -> Optional[Dict[str, Any]]:
        # get highest prio job
        if self.job_set.metadata.get(PRIORITIZATION_MODE) == "V0":
            job = sorted(
                self.job_set.jobs, key=lambda j: (j["priority"], j["createdAt"])
            )[0]
        else:
            job = sorted(self.job_set.jobs, key=lambda j: j["createdAt"])[0]

        # attempt to acquire lease
        lease_result = await self.job_set.lease_job(job["id"])
        if not lease_result:
            return None

        # confirm the item was removed from the job set
        await self.job_set.wait_for_update()
        if job in self.job_set.jobs:
            return None

        # if lease successful, return job from jobset
        return job

    async def ack_run_queue_item(self, item_id: str, run_id: str) -> bool:
        return await self.job_set.ack_job(item_id, run_id)

    async def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: Optional[List[str]] = None,
    ) -> bool:
        return await self.job_set.fail_job(
            run_queue_item_id, message, stage, file_paths
        )
