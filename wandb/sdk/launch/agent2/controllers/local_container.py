import asyncio
import json
import logging
from typing import Any, Dict

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.abstract import AbstractRun

from ...queue_driver import passthrough
from ...utils import MAX_CONCURRENCY
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet


async def local_container_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
):
    # disable job set loop because we are going to use the passthrough queue driver
    # to drive the launch controller here
    jobset.stop_sync_loop()

    name = config["jobset_spec"].name
    iter = 0
    max_concurrency = config["jobset_metadata"][MAX_CONCURRENCY]

    if max_concurrency is None or max_concurrency == "auto":
        # detect # of cpus available
        import multiprocessing

        max_concurrency = max(1, multiprocessing.cpu_count() - 1)
        logger.debug(
            f"Detecting max_concurrency as {max_concurrency} (based on # of CPUs available)"
        )

    logger.debug(
        f"Starting local container controller with max concurrency {max_concurrency}"
    )

    mgr = LocalContainerManager(config, jobset, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(5)
        iter += 1


class LocalContainerManager:
    """Maintains state for multiple docker containers."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        self.config = config
        self.logger = logger
        self.legacy = legacy
        self.max_concurrency = max_concurrency

        self.id = config["jobset_spec"].name
        self.active_runs: Dict[str, AbstractRun] = {}

        self.queue_driver = passthrough.PassthroughQueueDriver(
            api=jobset.api,
            queue_name=config["jobset_spec"].name,
            entity=config["jobset_spec"].entity_name,
            project=config["jobset_spec"].project_name,
            agent_id=config["agent_id"],
        )

    async def pop_next_item(self) -> Any:
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Popped item: {json.dumps(next_item, indent=2)}")
        return next_item

    async def reconcile(self):
        new_items = []
        num_runs_needed = self.max_concurrency - len(self.active_runs)
        if num_runs_needed > 0:
            for _ in range(num_runs_needed):
                # we own fewer items than our max concurrency, and there are other items waiting to be run
                # let's pop the next item
                item_to_run = await self.pop_next_item()
                if item_to_run is None:
                    break

                new_items.append(item_to_run)

        for item in new_items:
            # launch it
            await self.launch_item(item)

    async def launch_item(self, item: Any) -> Any:
        self.logger.info(f"Launching item: {json.dumps(item, indent=2)}")

        project = LaunchProject.from_spec(item["runSpec"], self.legacy.api)
        project.queue_name = self.config["jobset_spec"].name
        project.queue_entity = self.config["jobset_spec"].entity_name
        project.run_queue_item_id = item["runQueueItemId"]
        project.fetch_and_validate_project()
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        entrypoint = project.get_single_entry_point()
        assert entrypoint is not None
        image_uri = await self.legacy.builder.build_image(
            project, entrypoint, job_tracker
        )

        run = await self.legacy.runner.run(project, image_uri)
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item['id']}")
            raise NotImplementedError("TODO: handle this case")

        ack_result = await self.queue_driver.ack_run_queue_item(
            item["runQueueItemId"], run_id
        )
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")

        self.active_runs[item["runQueueItemId"]] = run
        self.logger.info(f"Inside launch_item, project.run_id = {run_id}")

        run_id = project.run_id
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def release_item(self, item: Any) -> Any:
        self.logger.info(f"Releasing item: {json.dumps(item, indent=2)}")
        del self.active_runs[item["runQueueItemId"]]
