import asyncio
import logging
from typing import Any, Awaitable, Dict, List, Optional, Set, TypedDict

from attr import dataclass

from wandb.apis.internal import Api
from wandb.sdk.launch.utils import event_loop_thread_exec


@dataclass
class JobSetSpec(TypedDict):
    name: str
    entity_name: str
    project_name: Optional[str]


JobSetId = str


def create_job_set(spec: JobSetSpec, api: Api, agent_id: str, logger: logging.Logger):
    # Retrieve the job set via Api.get_job_set_by_spec
    job_set_response = api.get_job_set_by_spec(
        job_set_name=spec["name"],
        entity_name=spec["entity_name"],
        project_name=spec["project_name"],
    )
    return JobSet(api, job_set_response, agent_id, logger)


class JobSet:
    def __init__(
        self, api: Api, job_set: Dict[str, Any], agent_id: str, logger: logging.Logger
    ):
        self.api = api
        self.agent_id = agent_id

        self.id = job_set["id"]
        self.name = job_set["name"]
        self._metadata = None
        self._lock = asyncio.Lock()

        self._logger = logger
        self._jobs: Set = set()
        self._ready_event = asyncio.Event()
        self._updated_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._done_event = asyncio.Event()
        self._poll_now_event = asyncio.Event()
        self._next_poll_interval = 5

        self._task = None
        self._last_state = None

    @property
    def lock(self):
        return self._lock

    @property
    def jobs(self):
        return self._jobs.copy()

    @property
    def metadata(self):
        return self._metadata.copy()

    @property
    async def wait_for_done(self):
        return await self._done_event.wait()

    async def wait_for_update(self):
        await self._updated_event.wait()
        self._updated_event.clear()

    async def _sync_loop(self):
        while not self._shutdown_event.is_set():
            await self._sync()
            await asyncio.wait(
                [self._poll_now_event.wait(), asyncio.sleep(self._next_poll_interval)],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._poll_now_event.is_set():
                self._poll_now_event.clear()
        self._logger.debug(f"[JobSet {self.name or self.id}] Sync loop exited.")
        self._done_event.set()

    async def _sync(self):
        self._logger.debug(f"[JobSet {self.name or self.id}] Updating...")
        next_state = await self._refresh_job_set()
        self._last_state = next_state
        self._metadata = next_state["metadata"]
        async with self.lock:
            self._jobs.clear()
            for job in self._last_state["jobs"]:
                self._jobs[job["id"]] = job
                # self._logger.debug(f'[JobSet {self.name or self.id}] Updated Job {job["id"]}')
        self._logger.debug(f"[JobSet {self.name or self.id}] Done.")
        self._ready_event.set()
        self._updated_event.set()

    async def _refresh_job_set(self):
        get_job_set_by_id = event_loop_thread_exec(self.api.get_job_set_by_id)
        return await get_job_set_by_id(self.id)

    def _poll_now(self):
        self._poll_now_event.set()

    def start_sync_loop(self, loop: asyncio.AbstractEventLoop):
        if self._task is None:
            self._loop = loop
            self._shutdown_event.clear()
            self._logger.debug(f"[JobSet {self.name or self.id}] Starting sync loop")
            self._task = self._loop.create_task(self._sync_loop())
        else:
            raise RuntimeError("Tried to start JobSet but already started")

    def stop_sync_loop(self):
        if self._task is not None:
            self._logger.debug(f"[JobSet {self.name or self.id}] Stopping sync loop")
            self._shutdown_event.set()
            self._poll_now_event.set()
            self._task = None
        else:
            raise RuntimeError("Tried to stop JobSet but not started")

    async def ready(self) -> None:
        await self._ready_event.wait()

    async def lease_job(self, job_id: str) -> Awaitable[bool]:
        lease_job_set_item = event_loop_thread_exec(self.api.lease_job_set_item)
        result = await lease_job_set_item(self.id, job_id, self.agent_id)
        if result:
            self._poll_now()
        return result

    async def ack_job(self, job_id: str, run_name: str) -> Awaitable[bool]:
        ack_job_set_item = event_loop_thread_exec(self.api.ack_job_set_item)
        result = await ack_job_set_item(self.id, job_id, self.agent_id, run_name)
        if result:
            self._poll_now()
        return result

    async def fail_job(
        self,
        job_id: str,
        message: str,
        stage: str,
        file_paths: Optional[List[str]] = None,
    ) -> Awaitable[bool]:
        fail_run_queue_item = event_loop_thread_exec(self.api.fail_run_queue_item)
        result = await fail_run_queue_item(job_id, message, stage, file_paths)
        if result:
            self._poll_now()
        return result
