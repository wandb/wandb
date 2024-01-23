import logging
from typing import Any, Dict, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.agent2.job_set import JobSet
from wandb.sdk.launch.queue_driver.abstract import AbstractQueueDriver
from wandb.sdk.launch.utils import PRIORITIZATION_MODE

logger = logging.getLogger(__name__)


class StandardQueueDriver(AbstractQueueDriver):
    def __init__(self, api: Api, job_set: JobSet):
        self.api = api
        self.job_set = job_set

    def pop_from_run_queue(self) -> Optional[Dict[str, Any]]:
        # get highest prio job
        if self.job_set.metadata.get(PRIORITIZATION_MODE) == "V0":
            job = sorted(
                self.job_set.jobs, key=lambda j: (j["priority"], j["createdAt"])
            )[0]
        else:
            job = sorted(self.job_set.jobs, key=lambda j: j["createdAt"])[0]

        # attempt to acquire lease
        lease_result = self.job_set.lease_job(job["id"])
        if not lease_result:
            return

        # if lease successful, return job from jobset
        return job

    def ack_run_queue_item(self, job_id: str, run_name: str) -> bool:
        return self.job_set.ack_job(job_id, run_name)

    def fail_run_queue_item(self, job_id: str, run_name: str) -> bool:
        return self.job_set.ack_job(job_id, run_name)
