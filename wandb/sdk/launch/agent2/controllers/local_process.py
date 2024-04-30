import asyncio
import json
import logging
from typing import Any, List, Optional, Union

from ..._project_spec import LaunchProject
from ...queue_driver import passthrough
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet, JobWithQueue
from .base import BaseManager, RunWithTracker


async def local_process_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
    agent_queue: asyncio.Queue[JobWithQueue],
) -> Any:
    # disable job set loop because we are going to use the passthrough queue driver
    # to drive the launch controller here
    jobset.stop_sync_loop()

    logger.debug(f"received config: {config}")

    iter = 0
    max_concurrency = config["jobset_metadata"]["@max_concurrency"]

    if max_concurrency is None or max_concurrency == "auto":
        # detect # of cpus available
        import multiprocessing

        max_concurrency = max(1, multiprocessing.cpu_count() - 1)
        logger.debug(
            f"Detecting max_concurrency as {max_concurrency} (based on # of CPUs available)"
        )

    logger.debug(
        f"Starting local process controller with max concurrency {max_concurrency}"
    )

    mgr = LocalProcessManager(
        config, jobset, logger, legacy, agent_queue, max_concurrency
    )

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1
    logger.debug("Shutdown complete")
    return None


class LocalProcessManager(BaseManager):
    """Maintains state for multiple local processes."""

    resource_type = "local-process"

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        agent_queue: asyncio.Queue,
        max_concurrency: int,
    ):
        self.queue_driver: passthrough.PassthroughQueueDriver = (
            passthrough.PassthroughQueueDriver(
                api=jobset.api,
                queue_name=config["jobset_spec"].name,
                entity=config["jobset_spec"].entity_name,
                project=config["jobset_spec"].project_name,
                agent_id=config["agent_id"],
            )
        )
        super().__init__(config, jobset, logger, legacy, agent_queue, max_concurrency)

    async def reconcile(self) -> None:
        num_runs_needed = self.max_concurrency - len(self.active_runs)
        if num_runs_needed > 0:
            for _ in range(num_runs_needed):
                # we own fewer items than our max concurrency, and there are other items waiting to be run
                # let's pop the next item
                item_to_run = await self.pop_next_item()
                if item_to_run is None:
                    # no more items to run
                    return
                asyncio.create_task(self.launch_item(item_to_run))

    async def launch_item(self, item: Job) -> Optional[str]:
        self.logger.info(f"Launching item: {item}")

        project = self._populate_project(item)
        project.fetch_and_validate_project()
        run_id = await self._launch_job(item, project)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def launch_scheduler_item(self, item: JobWithQueue) -> Optional[str]:
        self.logger.info(f"Launching item: {item}")

        project = self._populate_project(item)
        project.fetch_and_validate_project()

        run_id = await self._launch_job(item.job, project)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    def _populate_project(self, job: Union[Job, JobWithQueue]) -> LaunchProject:
        project = None
        if isinstance(job, JobWithQueue):
            project = LaunchProject.from_spec(job.job.run_spec, self.legacy.api)
            queue_name = job.queue
            queue_entity = job.entity
            job_id = job.job.id
        else:
            project = LaunchProject.from_spec(job.run_spec, self.legacy.api)
            queue_name = self.config["jobset_spec"].name
            queue_entity = self.config["jobset_spec"].entity_name
            job_id = job.id
        project.queue_name = queue_name
        project.queue_entity = queue_entity
        project.run_queue_item_id = job_id
        return project

    def _get_job(self, item: Union[Job, JobWithQueue]) -> Job:
        if isinstance(item, JobWithQueue):
            return item.job
        return item

    async def _launch_job(self, job: Job, project: LaunchProject) -> Optional[str]:
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id, project.queue_name)
        job_tracker.update_run_info(project)

        # note since we ack on rqi id the queue driver will handle acking the run queue item
        # even if its not for the specified queue
        ack_result = await self.queue_driver.ack_run_queue_item(job.id, run_id)
        if ack_result is None:
            self.logger.error(f"Failed to ack item {job.id}")
            return None
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
        run = await self.legacy.runner.run(project, "")  # image is unused
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {job.id}")
            raise NotImplementedError("TODO: handle this case")

        self.active_runs[job.id] = RunWithTracker(run, job_tracker)

        run_id = project.run_id
        return run_id

    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError

    def label_job(self, project: LaunchProject) -> None:
        pass
