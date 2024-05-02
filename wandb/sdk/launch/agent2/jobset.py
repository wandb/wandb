import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, List, Optional

from wandb.apis.internal import Api
from wandb.sdk.launch.utils import event_loop_thread_exec


@dataclass
class JobSetSpec:
    name: str
    entity_name: str
    project_name: Optional[str]
    # TODO: set queue_id to be used when labelling launched jobs
    # blocked on launch agent query returning queues instead of raw ids
    # queue_id: str


@dataclass
class JobSetDiff:
    version: int
    complete: bool
    metadata: Dict[str, Any]
    upsert_jobs: List[Dict[str, Any]]
    remove_jobs: List[str]


def create_jobset(spec: JobSetSpec, api: Api, agent_id: str, logger: logging.Logger):
    jobset_response = api.get_jobset_by_spec(
        jobset_name=spec.name,
        entity_name=spec.entity_name,
        project_name=spec.project_name,
        agent_id=agent_id,
    )
    return JobSet(api, jobset_response, agent_id, logger)


@dataclass
class Job:
    id: str
    run_spec: Dict[str, Any]
    state: str
    priority: int
    preemptible: bool
    can_preempt: bool
    created_at: str
    claimed_by: str


"""
Used with SchedulerController to provide the queue
on which the job is to be run.
"""


@dataclass
class JobWithQueue:
    job: Job
    queue: str
    entity: str


def run_queue_item_to_job(run_queue_item: Dict[str, Any]) -> Job:
    return Job(
        id=run_queue_item["id"],
        run_spec=run_queue_item["runSpec"],
        state=run_queue_item["state"],
        priority=run_queue_item["priority"],
        preemptible=run_queue_item["priority"] > 0,
        can_preempt=run_queue_item["priority"] == 0,
        created_at=run_queue_item["createdAt"],
        claimed_by=run_queue_item.get("launchAgentId", None),
    )


class JobSet:
    _task: Optional[asyncio.Task] = None

    def __init__(
        self, api: Api, jobset: Dict[str, Any], agent_id: str, logger: logging.Logger
    ):
        self.api = api
        self.agent_id = agent_id

        self.id = jobset["metadata"]["@id"]
        self.name = jobset["metadata"]["@name"]
        self._metadata = jobset["metadata"]
        self._lock = asyncio.Lock()

        self._logger = logger
        self._jobs: Dict[str, Job] = dict()
        self._ready_event = asyncio.Event()
        self._updated_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._done_event = asyncio.Event()
        self._poll_now_event = asyncio.Event()
        self._next_poll_interval = 5

        self._task = None
        self._last_state: Optional[JobSetDiff] = None

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
        self._updated_event.clear()
        await self._updated_event.wait()

    @property
    def jobset_diff_version(self):
        if self._last_state is None:
            return -1
        return self._last_state.version

    async def _poll_now_task(self):
        return await self._poll_now_event.wait()

    async def _sync_loop(self):
        while not self._shutdown_event.is_set():
            try:
                await self._sync()
                wait_task = asyncio.create_task(self._poll_now_task())
                await asyncio.wait(
                    [wait_task],
                    timeout=self._next_poll_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self._poll_now_event.is_set():
                    self._poll_now_event.clear()
            except Exception as e:
                self._logger.exception(e)
                await asyncio.sleep(5)
        self._logger.info("Sync loop exited.")
        self._done_event.set()

    async def _sync(self):
        next_state = await self._refresh_jobset()
        self._logger.debug(f"State: {next_state}")

        # just grabbed a diff from the server, now to add to our local state
        self._last_state = next_state

        # TODO: make this sicker
        # self._metadata = next_state.metadata
        async with self.lock:
            for job in self._last_state.upsert_jobs:
                _job = run_queue_item_to_job(job)
                self._jobs[_job.id] = _job
                self._logger.debug(f"Upsert Job: {_job.id}")

            for job_id in self._last_state.remove_jobs:
                if not self._jobs.pop(job_id, False):
                    self._logger.warn(f"Delete Job {job_id}, but it doesn't exist")
                    continue
                self._logger.debug(f"Deleted Job {job_id}")
        self._ready_event.set()
        self._updated_event.set()

    async def _refresh_jobset(self) -> JobSetDiff:
        get_jobset_diff_by_id = event_loop_thread_exec(self.api.get_jobset_diff_by_id)
        diff = await get_jobset_diff_by_id(
            self.id, self.jobset_diff_version, self.agent_id
        )
        return JobSetDiff(
            version=diff["version"],
            complete=diff["complete"],
            metadata=diff["metadata"],
            upsert_jobs=diff["upsertJobs"],
            remove_jobs=diff["removeJobs"],
        )

    def _poll_now(self):
        self._poll_now_event.set()

    def start_sync_loop(self, loop: asyncio.AbstractEventLoop):
        if self._task is None:
            self._loop = loop
            self._shutdown_event.clear()
            self._logger.debug("Starting sync loop")
            self._task = self._loop.create_task(self._sync_loop())
        else:
            raise RuntimeError("Tried to start JobSet but already started")

    def stop_sync_loop(self):
        if self._task is not None:
            self._logger.debug("Stopping sync loop")
            self._shutdown_event.set()
            self._poll_now_event.set()
            self._task = None
        else:
            raise RuntimeError("Tried to stop JobSet but not started")

    async def ready(self) -> None:
        await self._ready_event.wait()

    async def lease_job(self, job_id: str) -> Awaitable[bool]:
        lease_jobset_item = event_loop_thread_exec(self.api.lease_jobset_item)
        result = await lease_jobset_item(self.id, job_id, self.agent_id)
        if result:
            self._poll_now()
        return result

    async def ack_job(self, job_id: str, run_name: str) -> Awaitable[bool]:
        ack_jobset_item = event_loop_thread_exec(self.api.ack_jobset_item)
        result = await ack_jobset_item(self.id, job_id, self.agent_id, run_name)
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
