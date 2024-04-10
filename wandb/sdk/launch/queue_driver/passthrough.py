from typing import List, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.utils import event_loop_thread_exec

from ..agent2.jobset import Job, run_queue_item_to_job
from .abstract import AbstractQueueDriver


class PassthroughQueueDriver(AbstractQueueDriver):
    """PassthroughQueueDriver does not use a local jobset, instead acts as a simple proxy to the original backend.

    Useful for queue types that support or need multiple agents and need the backend to manage the queue.
    """

    queue_name: str
    entity: Optional[str]
    project: Optional[str]
    agent_id: Optional[str]

    def __init__(
        self,
        api: Api,
        queue_name: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        self.api = api
        self.queue_name = queue_name
        self.entity = entity
        self.project = project
        self.agent_id = agent_id

    async def pop_from_run_queue(self) -> Optional[Job]:
        def _rq_pop():
            res = self.api.pop_from_run_queue(
                self.queue_name, self.entity, self.project, self.agent_id
            )
            if res is not None:
                rqi = self.api.get_run_queue_item(
                    self.entity, self.queue_name, res["runQueueItemId"]
                )
                if rqi is None:
                    raise ValueError(
                        f"Failed to get run queue item {res['runQueueItemId']}"
                    )
                return run_queue_item_to_job(rqi)
            return None

        return await event_loop_thread_exec(_rq_pop)()

    async def ack_run_queue_item(
        self, item_id: str, run_id: Optional[str] = None
    ) -> bool:
        def _rq_ack():
            return self.api.ack_run_queue_item(item_id, run_id)

        return await event_loop_thread_exec(_rq_ack)()

    async def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: Optional[List[str]] = None,
    ) -> bool:
        def _rqi_fail():
            return self.api.fail_run_queue_item(
                run_queue_item_id,
                message,
                stage,
                file_paths,
            )

        return await event_loop_thread_exec(_rqi_fail)()
