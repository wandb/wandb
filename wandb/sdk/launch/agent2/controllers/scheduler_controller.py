import asyncio
import logging
from typing import Any, Dict, Optional, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch._project_spec import LaunchProject

from ...utils import LOG_PREFIX, event_loop_thread_exec
from ..controller import LegacyResources
from ..jobset import Job, JobWithQueue
from .base import RunWithTracker
from .local_process import LocalProcessManager


async def scheduler_process_controller(
    manager: "SchedulerManager",
    max_schedulers: int,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    scheduler_jobs_queue: "asyncio.Queue[JobWithQueue]",
) -> Any:
    iter = 0

    logger.debug(f"Starting scheduler manager with max schedulers {max_schedulers}")

    mgr = SchedulerController(manager, max_schedulers, scheduler_jobs_queue, logger)

    while not shutdown_event.is_set():
        await mgr.poll()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1
    logger.debug("Shutdown complete")
    return None


class SchedulerController:
    def __init__(
        self,
        manager: LocalProcessManager,
        max_schedulers: int,
        scheduler_jobs_queue: "asyncio.Queue[JobWithQueue]",
        logger: logging.Logger,
    ):
        self._manager = manager
        self._scheduler_jobs_queue = scheduler_jobs_queue
        self._logger = logger
        self._max_schedulers = max_schedulers

    async def poll(self):
        job = await self._scheduler_jobs_queue.get()
        if job is None:
            return
        if len(self.active_runs) >= self._max_schedulers:
            self._logger.info(f"Scheduler job queue is full, skipping job: {job}")
            wandb.termwarn(
                f"{LOG_PREFIX}Agent already running the maximum number "
                f"of sweep schedulers: {self._max_schedulers}. To set "
                "this value use `max_schedulers` key in the agent config"
            )
            return
        asyncio.create_task(self._manager.launch_scheduler_item(job))
        self._logger.info(f"Launched scheduler job: {job}")

    @property
    def active_runs(self):
        return self._manager.active_runs


class SchedulerManager(LocalProcessManager):
    def __init__(
        self,
        api: Api,
        max_schedulers: int,
        legacy: LegacyResources,
        scheduler_jobs_queue: "asyncio.Queue[JobWithQueue]",
        logger: logging.Logger,
    ):
        self._api = api
        self.legacy = legacy
        self._max_schedulers = max_schedulers
        self._scheduler_jobs_queue = scheduler_jobs_queue
        self.logger = logger
        self.active_runs: Dict[str, RunWithTracker] = {}

    async def ack_run_queue_item(self, queue_item: str, run_id: str):
        ack_func = event_loop_thread_exec(self._api.ack_run_queue_item)
        return await ack_func(queue_item, run_id)

    async def launch_scheduler_item(self, item: JobWithQueue) -> Optional[str]:
        self.logger.info(f"Launching item: {item}")
        print("LAUNCHING SCHEDULER")
        project = self._populate_project(item)
        project.fetch_and_validate_project()

        run_id = await self._launch_job(item.job, project)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    def _populate_project(self, job: Union[Job, JobWithQueue]) -> LaunchProject:
        assert isinstance(job, JobWithQueue)
        project = LaunchProject.from_spec(job.job.run_spec, self.legacy.api)
        queue_name = job.queue
        queue_entity = job.entity
        job_id = job.job.id
        project.queue_name = queue_name
        project.queue_entity = queue_entity
        project.run_queue_item_id = job_id
        return project
