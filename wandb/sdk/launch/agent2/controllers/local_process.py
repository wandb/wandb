import asyncio
import json
import logging
from typing import Any, Awaitable, Dict
from ...queue_driver import passthrough

from wandb.sdk.launch.runner.abstract import AbstractRun
from wandb.sdk.launch._project_spec import (
    create_project_from_spec,
    fetch_and_validate_project,
)


from ..controller import LaunchControllerConfig, LegacyResources
from ..job_set import JobSet

QUEUE_TYPE = "local-process"


async def local_process_controller(
    config: LaunchControllerConfig,
    job_set: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
) -> Awaitable[Any]:
    # disable job set loop because we are going to use the passthrough queue driver
    # to drive the launch controller here
    job_set.stop_sync_loop()

    name = config["job_set_spec"]["name"]
    iter = 0
    max_concurrency = config["job_set_metadata"]["@max_concurrency"]

    if max_concurrency is None or max_concurrency == "auto":
        # detect # of cpus available
        import multiprocessing

        max_concurrency = max(1, multiprocessing.cpu_count() - 1)
        logger.debug(
            f"[Controller {name}] Detecting max_concurrency as {max_concurrency} (based on # of CPUs available)"
        )

    logger.debug(
        f"[Controller {name}] Starting local process controller with max concurrency {max_concurrency}"
    )

    mgr = LocalProcessesManager(config, job_set, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1
    logger.debug(f"[Controller {name}] Cleaning up...")

    await asyncio.sleep(2)  # TODO: get rid of this
    logger.debug(f"[Controller {name}] Done!")


class LocalProcessesManager:
    """Maintains state for multiple local processes."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        job_set: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        self.config = config
        self.logger = logger
        self.legacy = legacy
        self.max_concurrency = max_concurrency

        self.id = config["job_set_spec"]["name"]
        self.active_runs: Dict[str, AbstractRun] = {}

        self.queue_driver = passthrough.PassthroughQueueDriver(
            job_set.api,
            config["job_set_spec"]["entity_name"],
            config["job_set_spec"]["project_name"],
            config["agent_id"],
        )

    async def pop_next_item(self) -> Any:
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f" item: {json.dumps(next_item, indent=2)}")
        return next_item

    async def reconcile(self):
        new_items = []
        num_runs_needed = self.max_concurrency - len(self.active_runs)
        if num_runs_needed > 0:
            for _ in range(num_runs_needed):
                # we own fewer items than our max concurrency, and there are other items waiting to be run
                # let's pop the next item
                item_to_run = await self.pop_next_item()
                new_items.append(item_to_run)

        for item in new_items:
            # launch it
            await self.launch_item(item)

    async def launch_item(self, item: Any) -> Any:
        self.logger.info(f"Launching item: {json.dumps(item, indent=2)}")

        project = create_project_from_spec(item["runSpec"], self.legacy.api)
        project.queue_name = self.config["job_set_spec"]["name"]
        project.queue_entity = self.config["job_set_spec"]["entity_name"]
        project.run_queue_item_id = item["id"]
        project = fetch_and_validate_project(project, self.legacy.api)
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        run = await self.legacy.runner.run(project, project.docker_image)
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item['id']}")
            raise NotImplementedError("TODO: handle this case")

        ack_result = await self.queue_driver.ack_run_queue_item(item["id"], run_id)
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")

        self.active_runs[item["id"]] = run
        self.logger.info(f"Inside launch_item_task, project.run_id = {run_id}")

        run_id = project.run_id
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id
