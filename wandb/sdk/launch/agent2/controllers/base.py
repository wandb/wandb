import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.abstract import AbstractRun

from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet

class BaseManager(ABC):
    """Maintains state for multiple jobs."""

    @abstractmethod
    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        raise NotImplementedError
        # TODO: handle orphaned jobs in resource and assign to self

    async def reconcile(self) -> None:
        raw_items = list(self.jobset.jobs.values())

        # Dump all raw items
        self.logger.info(
            f"====== Raw items ======\n{json.dumps(raw_items, indent=2)}\n======================"
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
        for item in self.active_runs:
            if item not in owned_items:
                # we don't own this item anymore
                await self.release_item(item)

    async def pop_next_item(self) -> Optional[Job]:
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Leased item: {json.dumps(next_item, indent=2)}")
        return next_item

    async def launch_item(self, item: Job) -> Optional[str]:
        run_id = await self.launch_item_task(item)
        self.logger.info(f"Launched item got run_id: {run_id}")
        return run_id

    async def launch_item_task(self, item: Job) -> Optional[str]:
        self.logger.info(f"Launching item: {json.dumps(item, indent=2)}")

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
        run = await self.legacy.runner.run(project, image_uri)
        if not run:
            job_tracker.failed_to_start = True
            self.logger.error(f"Failed to start run for item {item.id}")
            raise NotImplementedError("TODO: handle this case")

        self.active_runs[item.id] = run
        self.logger.info(f"Inside launch_item_task, project.run_id = {run_id}")
        return project.run_id

    async def release_item(self, item: str) -> None:
        self.logger.info(f"Releasing item: {item}")
        del self.active_runs[item]

    @abstractmethod
    async def find_orphaned_jobs(self) -> None:
        pass

    @abstractmethod
    async def cleanup_removed_jobs(self) -> None:
        pass

    @abstractmethod
    async def label_jobs(self) -> None:
        pass