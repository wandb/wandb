import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner.abstract import AbstractRun
from wandb.sdk.lib.hashutil import b64_to_hex_id, md5_string

from ...queue_driver.abstract import AbstractQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet

WANDB_JOBSET_DISCOVERABILITY_LABEL = "_wandb-jobset"


class BaseManager(ABC):
    """Maintains state for multiple jobs."""

    queue_driver: Optional[AbstractQueueDriver] = None
    resource_type: str

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
        if self.queue_driver is None:
            raise LaunchError(
                "queue_driver is not set, set queue driver in subclass constructor"
            )

    async def reconcile(self) -> None:
        assert self.queue_driver is not None
        raw_items = list(self.jobset.jobs.values())
        # Dump all raw items
        self.logger.info(
            f"====== Raw items ======\n{raw_items}\n======================"
        )

        owned_items = {
            item.id: item
            for item in raw_items
            if item.state in ["LEASED", "CLAIMED"]
            and item.claimed_by == self.config["agent_id"]
        }

        if len(owned_items) < self.max_concurrency:
            # we own fewer items than our max concurrency, and there are other items waiting to be run
            # let's lease the next item
            next_item = await self.pop_next_item()
            if next_item is not None:
                owned_items[next_item.id] = next_item

        # ensure all our owned items are running
        for owned_item_id in owned_items:
            if owned_item_id not in self.active_runs:
                # we own this item but it's not running
                await self.launch_item(owned_items[owned_item_id])

        # TODO: validate job set clears finished runs
        # release any items that are no longer in owned items
        for item in list(self.active_runs):
            if item not in owned_items:
                # we don't own this item anymore
                await self.cancel_job(item)
                await self.release_item(item)

    async def pop_next_item(self) -> Optional[Job]:
        assert self.queue_driver is not None
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Leased item: {next_item}")
        return next_item

    async def launch_item(self, item: Job) -> Optional[str]:
        self.logger.info(f"Launching item: {item}")
        assert self.queue_driver is not None

        project = LaunchProject.from_spec(item.run_spec, self.legacy.api)
        project.queue_name = self.config["jobset_spec"].name
        project.queue_entity = self.config["jobset_spec"].entity_name
        project.run_queue_item_id = item.id
        project.fetch_and_validate_project()
        run_id = project.run_id
        job_tracker = self.legacy.job_tracker_factory(run_id)
        job_tracker.update_run_info(project)

        ack_result = await self.jobset.ack_job(item.id, run_id)
        self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
        if not ack_result:
            self.logger.error(f"Failed to ack item: {item.id}")
            return None
        image_uri = None
        if not project.docker_image:
            entrypoint = project.get_single_entry_point()
            assert entrypoint is not None
            image_uri = await self.legacy.builder.build_image(
                project, entrypoint, job_tracker
            )
        else:
            assert project.docker_image is not None
            image_uri = project.docker_image

        assert image_uri is not None
        self.label_job(project)
        run = await self.legacy.runner.run(project, image_uri)
        if not run:
            job_tracker.failed_to_start = True
            await self.release_item(item.id)
            self.logger.error(f"Failed to start run for item {item.id}")
            raise NotImplementedError("TODO: handle this case")
        self.active_runs[item.id] = run

        self.logger.info(f"Inside launch_item, project.run_id = {run_id}")
        return project.run_id

    async def release_item(self, item_id: str) -> None:
        self.logger.info(f"Releasing item: {item_id}")
        del self.active_runs[item_id]

    def _construct_jobset_discoverability_label(self) -> str:
        return b64_to_hex_id(
            md5_string(
                f"{self.config['jobset_spec'].entity_name}/{self.config['jobset_spec'].name}"
            )
        )

    async def cancel_job(self, item: str) -> None:
        run = self.active_runs[item]
        status = None
        try:
            status = await run.get_status()
        except Exception as e:
            self.logger.error(f"Error getting status for run {run.id}: {e}")
            return
        if status == "running":
            try:
                await run.cancel()
            except Exception as e:
                self.logger.error(f"Error stopping run {run.id}: {e}")

    def _get_resource_block(self, project: LaunchProject) -> Optional[Dict[str, Any]]:
        return project.resource_args.get(self.resource_type, None)

    @abstractmethod
    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError

    @abstractmethod
    def label_job(self, project: LaunchProject) -> None:
        raise NotImplementedError
