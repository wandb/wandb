import asyncio
import json
import logging
from typing import Any, Dict

from wandb.sdk.launch.runner.abstract import AbstractRun

from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet
from .util import parse_max_concurrency

DEFAULT_MAX_CONCURRENCY = 1000


async def sagemaker_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
):
    iter = 0
    max_concurrency = parse_max_concurrency(config, DEFAULT_MAX_CONCURRENCY)

    logger.debug(
        f"Starting SageMaker controller with max_concurrency={max_concurrency}"
    )

    mgr = SageMakerManager(config, jobset, logger, legacy)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(5)
        iter += 1

    return None


class SageMakerManager:
    """Maintains state for multiple SageMaker jobs."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        self.config = config
        self.jobset = jobset
        self.logger = logger
        self.legacy = legacy
        self.max_concurrency = max_concurrency

        self.id = config["jobset_spec"].name
        self.active_runs: Dict[str, AbstractRun] = {}

    async def reconcile(self):
        raw_items = list(self.jobset.jobs.values())
        self.logger.info(
            f"===== Raw items ===== \n{json.dumps(raw_items, indent=2)}\n================"
        )

        owned_items = [
            item
            for item in raw_items
            if item["state"] in ["LEASED", "CLAIMED"]
            and item["launchAgenbtId"] == self.config["agent_id"]
        ]

        # TODO: this is wrong, need to also know lease time and account for that
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
                await self.launch_item(item)

        for item in self.active_runs:
            if item not in owned_items:
                await self.release_item(item)

    async def lease_next_item(self) -> None:
        raw_items = list(self.jobset.jobs.values())
        pending_items = [item for item in raw_items if item["state"] in ["PENDING"]]

        if len(pending_items) == 0:
            return None

        sorted_items = sorted(
            pending_items, key=lambda item: (item["priority"], item["createdAt"])
        )
        self.logger.info(f"Next item: {json.dumps(sorted_items[0], indent=2)}")
        lease_result = await self.jobset.lease_job(sorted_items[0]["id"])
        self.logger.info(f"Leased item {json.dumps(lease_result, indent=2)}")

    async def launch_item(self, item: Any) -> str:
        run_id = await self.launch_item_task(item)
        self.logger.info(f"Lauinch item go run_id: {run_id}")
        return run_id
