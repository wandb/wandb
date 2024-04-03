from ast import Not
import asyncio
import json
import logging
from typing import Any, Awaitable, Dict, Optional

from wandb.sdk.launch.runner.abstract import AbstractRun

from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet
from .util import parse_max_concurrency
from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..._project_spec import LaunchProject

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
        self.queue_driver = StandardQueueDriver(jobset.api, jobset)


        # TODO: find orphaned jobs in resource and assign to self

    async def get_session(self) -> Any:
        session = await self.legacy.environment.get_session()

    
    async def pop_next_itemm(self) -> Awaitable[Optional[Dict[str, Any]]]:
        next_item = self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Popped item: {json.dumps(next_item, indent=2)}")
        return next_item
    
    async def release_item(self, item: Job) -> None:
        self.logger.info(f"Releasing item: {json.dumps(item, indent=2)}")
        del self.active_runs(item.id)

    
    async def reconcile(self):
        raw_items = list(self.jobset.jobs.values())
        self.logger.info(
            f"===== Raw items ===== \n{json.dumps(raw_items, indent=2)}\n================"
        )

        owned_items = [
            item
            for item in raw_items
            if item.state in ["CLAIMED", "LEASED"]
            and item.claimed_by == self.config["agent_id"]
        ]
        # TODO: validate that lease expirations are set back to PENDING
        pending_items = [item for item in raw_items if item.state == "PENDING"]
        self.logger.info(
            f"Reconciling {len(owned_items)} owned items and {len(pending_items)} pending items"
        )

        if len(owned_items) < self.max_concurrency and len(pending_items) > 0:
            # we own fewer items than our max concurrency, and there are other items waiting to be run
            # let's lease the next item
            next_item = await self.pop_next_item()
            owned_items.append(next_item)

        # ensure all our owned items are running
        for item in owned_items:
            if item.id not in self.active_runs:
                await self.launch_item(item)

        # TODO: ensure JobSet removes completed runs from the set
        for item in self.active_runs:
            if item not in owned_items:
                await self.release_item(item)


    async def launch_item(self, item: Job) -> Optional[str]:
        run_id = await self.launch_item_task(item)
        if not run_id:
            return None
        self.logger.info(f"Launch item got run_id: {run_id}")
        return run_id
    
    async def launch_item_task(self, item: Job) -> Optional[str]:
        self.logger.info(f"Lauinch item: {json.dumps(item, indent=2)}")
        project = LaunchProject.from_spec(item.run_spec, self.legacy.api)
        project.queue_name = self.config["jobset_spec"].queue_name
        project.queue_entity = self.config["jobset_spec"].entity_name
        project.run_queue_item_id = item.id
        project.fetch_and_validate_project()
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        ack_result = await self.queue_driver.ack_run_queue_item(item.id, run_id)
        if not ack_result:
            return None
        self.logger.info(f"Acknowledged item: {item.id} with run_id: {run_id}")

        image_uri = None
        if not project.docker_image:
            entrypoint = project.get_single_entry_point()
            assert entrypoint is not None
            image_uri = await self.legacy.builder.build_image(project, entrypoint, job_tracker)
        else:
            assert project.docker_image is not None
            image_uri = project.docker_image
        run = await self.legacy.runner.run(
            project,
            image_uri
        )
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item.id}")
            raise NotImplementedError("TODO: handle this case")
        
        self.active_runs[item.id] = run
        return run_id

