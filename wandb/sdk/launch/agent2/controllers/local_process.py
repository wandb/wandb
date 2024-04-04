import asyncio
import json
import logging
from typing import Any, List, Optional

from wandb.sdk.launch._project_spec import LaunchProject

from ...queue_driver import passthrough
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet
from .base import BaseManager


async def local_process_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
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

    mgr = LocalProcessesManager(config, jobset, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1
    logger.debug("Shutdown complete")
    return None


class LocalProcessesManager(BaseManager):
    """Maintains state for multiple local processes."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
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
        super().__init__(config, jobset, logger, legacy, max_concurrency)

    async def pop_next_item(self) -> Optional[Job]:
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f" item: {json.dumps(next_item, indent=2)}")
        return next_item

    async def reconcile(self) -> None:
        num_runs_needed = self.max_concurrency - len(self.active_runs)
        if num_runs_needed > 0:
            for _ in range(num_runs_needed):
                # we own fewer items than our max concurrency, and there are other items waiting to be run
                # let's pop the next item
                item_to_run = await self.pop_next_item()
                if item_to_run is None:
                    # no more items to run
                    break
                asyncio.create_task(self.launch_item(item_to_run))

    async def launch_item(self, item: Job) -> Optional[str]:
        self.logger.info(f"Launching item: {json.dumps(item, indent=2)}")

        project = LaunchProject.from_spec(item.run_spec, self.legacy.api)
        project.queue_name = self.config["jobset_spec"].name
        project.queue_entity = self.config["jobset_spec"].entity_name
        project.run_queue_item_id = item.id
        project.fetch_and_validate_project()

        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        ack_result = await self.queue_driver.ack_run_queue_item(item.id, run_id)
        if ack_result is None:
            self.logger.error(f"Failed to ack item {item.id}")
            return None
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
        run = await self.legacy.runner.run(project, "")  # image is unused
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item.id}")
            raise NotImplementedError("TODO: handle this case")

        self.active_runs[item.id] = run

        run_id = project.run_id
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError

    async def cleanup_removed_jobs(self) -> None:
        raise NotImplementedError

    async def label_jobs(self) -> None:
        raise NotImplementedError
