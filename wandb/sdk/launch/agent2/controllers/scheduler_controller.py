import asyncio
import logging
from typing import Any

import wandb

from ...utils import LOG_PREFIX
from ..jobset import JobWithQueue
from .local_process import LocalProcessManager


async def scheduler_process_controller(
    manager: LocalProcessManager,
    max_schedulers: int,
    scheduler_jobs_queue: "asyncio.Queue[JobWithQueue]",
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
) -> Any:
    iter = 0

    logger.debug(f"Starting scheduler manager with max schedulers {max_schedulers}")

    mgr = SchedulerManager(manager, max_schedulers, scheduler_jobs_queue, logger)

    while not shutdown_event.is_set():
        await mgr.poll()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1
    logger.debug("Shutdown complete")
    return None


class SchedulerManager:
    def __init__(
        self,
        controller: LocalProcessManager,
        max_schedulers: int,
        scheduler_jobs_queue: "asyncio.Queue[JobWithQueue]",
        logger: logging.Logger,
    ):
        self._controller = controller
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
        asyncio.create_task(self._controller.launch_scheduler_item(job))
        self._scheduler_jobs_queue.task_done()
        self._logger.info(f"Launched scheduler job: {job}")

    @property
    def active_runs(self):
        return self._controller.active_runs
