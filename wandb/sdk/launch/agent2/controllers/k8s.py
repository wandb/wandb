import asyncio
import json
import logging
from typing import Any, Dict, Optional

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.abstract import AbstractRun

from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet


async def k8s_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
) -> Any:
    iter = 0
    max_concurrency = config["jobset_metadata"]["@max_concurrency"]
    if max_concurrency is None or max_concurrency == "auto":
        max_concurrency = 1000
    else:
        try:
            max_concurrency = int(max_concurrency)
        except ValueError:
            raise ValueError(
                f"Invalid value for @max_concurrency: {max_concurrency}. Must be an integer or 'auto'."
            )

    logger.debug(
        f"Starting local process controller with max concurrency {max_concurrency}"
    )

    mgr = KubernetesManager(config, jobset, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1

    return None


class KubernetesManager:
    """Maintains state for multiple Kubernetes jobs."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
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
        self.queue_driver = StandardQueueDriver(jobset.api, jobset)

        # TODO: handle orphaned jobs in resource and assign to self

    async def reconcile(self):
        raw_items = list(self.jobset.jobs.values())

        # Dump all raw items
        self.logger.info(
            f"====== Raw items ======\n{json.dumps(raw_items, indent=2)}\n======================"
        )

        owned_items = {
            item.id: item
            for item in raw_items
            if item.state in ["LEASED", "CLAIMED"]
            and item["launchAgentId"] == self.config["agent_id"]
        }

        if len(owned_items) < self.max_concurrency:
            # we own fewer items than our max concurrency, and there are other items waiting to be run
            # let's lease the next item
            next_item = await self.pop_next_item()
            if next_item is not None:
                self.owned_items[next_item.id] = next_item

        # ensure all our owned items are running
        for item in owned_items:
            if item["id"] not in self.active_runs:
                # we own this item but it's not running
                await self.launch_item(item)

        # TODO: validate job set clears finished runs
        # release any items that are no longer in owned items
        for item in self.active_runs:
            if item not in owned_items:
                # we don't own this item anymore
                await self.release_item(item)

    async def pop_next_item(self) -> Optional[Job]:
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Leased item: {json.dumps(next_item, indent=2)}")
        return next_item

    async def launch_item(self, item: Any) -> Any:
        run_id = await self.launch_item_task(item)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def launch_item_task(self, item: Any) -> str:
        self.logger.info(f"Launching item: {json.dumps(item, indent=2)}")

        project = LaunchProject.from_spec(item["runSpec"], self.legacy.api)
        project.queue_name = self.config["jobset_spec"].name
        project.queue_entity = self.config["jobset_spec"].entity_name
        project.run_queue_item_id = item["id"]
        project.fetch_and_validate_project()
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        assert (
            project.docker_image is not None
        ), "Docker image must be set when using k8s"
        run = await self.legacy.runner.run(project, project.docker_image)
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item['id']}")
            raise NotImplementedError("TODO: handle this case")

        ack_result = await self.jobset.ack_job(item["id"], run_id)
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
        self.active_runs[item["id"]] = run
        self.logger.info(f"Inside launch_item_task, project.run_id = {run_id}")
        return project.run_id

    async def release_item(self, item: str) -> Any:
        self.logger.info(f"Releasing item: {item}")
        del self.active_runs[item]
