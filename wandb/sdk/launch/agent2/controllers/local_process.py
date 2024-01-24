import asyncio
import json
import logging
from typing import Any, Awaitable, Dict

from wandb.sdk.launch._project_spec import (
    create_project_from_spec,
    fetch_and_validate_project,
)
from wandb.sdk.launch.runner.abstract import AbstractRun
from wandb.sdk.launch.runner.local_container import LocalSubmittedRun

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
    name = config["job_set_spec"]["name"]
    entity_name = config["job_set_spec"]["entity_name"]
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
        await job_set.wait_for_update()
        await mgr.reconcile()
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
        self.job_set = job_set
        self.logger = logger
        self.legacy = legacy
        self.max_concurrency = max_concurrency
        runs: Dict[str, LocalSubmittedRun] = {}

        self.id = config["job_set_spec"]["name"]
        self.active_runs: Dict[str, AbstractRun] = {}

    async def reconcile(self):
        raw_items = list(self.job_set.jobs.values())

        # Dump all raw items
        formd = {item["id"]: item["state"] for item in raw_items}
        self.logger.info(
            f"====== Raw items ======\n{json.dumps(formd, indent=2)}\n======================"
        )

        owned_items = [
            item
            for item in raw_items
            if item["state"] in ["LEASED", "CLAIMED", "RUNNING"]
            and item["launchAgentId"] == self.config["agent_id"]
        ]
        pending_items = [item for item in raw_items if item["state"] in ["PENDING"]]

        self.logger.info(
            f"Reconciling {len(owned_items)} owned items and {len(pending_items)} pending items"
        )

        if len(owned_items) < self.max_concurrency and len(pending_items) > 0:
            # we own fewer items than our max concurrency, and there are other items waiting to be run
            # let's lease the next item
            await self.lease_next_item()

        # ensure all our owned items are running
        for item in owned_items:
            if item["id"] not in self.active_runs:
                if item["state"] == "CLAIMED":
                  # This can happen if the run finishes before we update the job set (ex. sub 5 second runtime)
                  self.logger.error(f"Item {item} is CLAIMED but not in self.active_runs!")
                  continue
                # we own this item but it's not running
                await self.launch_item(item)

        # release any items that are no longer in owned items
        to_delete = []
        for item in self.active_runs:
            if item not in owned_items:
                to_delete += [item]

        for item_id in to_delete:
          # we don't own this item anymore, delete
          await self.release_item(item_id)

    async def lease_next_item(self) -> Any:
        raw_items = list(self.job_set.jobs.values())
        pending_items = [item for item in raw_items if item["state"] in ["PENDING"]]
        if len(pending_items) == 0:
            return None

        sorted_items = sorted(
            pending_items, key=lambda item: (item["priority"], item["createdAt"])
        )
        next_item = sorted_items[0]
        self.logger.info(f"Next item: {json.dumps(next_item, indent=2)}")
        lease_result = await self.job_set.lease_job(next_item["id"])
        self.logger.info(f"Leased item: {json.dumps(lease_result, indent=2)}")

    async def launch_item(self, item: Any) -> Any:
        run_id = await self.launch_item_task(item)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def launch_item_task(self, item: Any) -> str:
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

        ack_result = await self.job_set.ack_job(item["id"], run_id)
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
        self.active_runs[item["id"]] = run
        self.logger.info(f"Inside launch_item_task, project.run_id = {run_id}")
        return project.run_id

    async def release_item(self, item_id: str) -> Any:
        self.logger.info(f"Releasing item: {json.dumps(item_id, indent=2)}")
        del self.active_runs[item_id]
