import asyncio
import logging
from typing import Any, Dict, List

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401

from wandb.sdk.launch.utils import event_loop_thread_exec
from wandb.util import get_module

from ..._project_spec import LaunchProject
from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet, JobWithQueue
from .base import BaseManager
from .util import parse_max_concurrency

# Required due to Vertex's limitations on label keys
WANDB_VERTEX_JOBSET_DISCOVERABILITY_LABEL = "wandb-jobset"


async def vertex_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
    scheduler_queue: "asyncio.Queue[JobWithQueue]",
) -> None:
    max_concurrency = parse_max_concurrency(config, 1000)

    logger.debug(f"Starting vertex controller with max concurrency {max_concurrency}")

    mgr = VertexManager(
        config, jobset, logger, legacy, scheduler_queue, max_concurrency
    )

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events

    return None


class VertexManager(BaseManager):
    """Maintains state for multiple Vertex jobs."""

    resource_type = "vertex"

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        scheduler_queue: "asyncio.Queue[JobWithQueue]",
        max_concurrency: int,
    ):
        self.queue_driver = StandardQueueDriver(jobset.api, jobset, logger)
        super().__init__(
            config, jobset, logger, legacy, scheduler_queue, max_concurrency
        )
        # TODO: handle orphaned jobs in resource and assign to self (can do
        # this because we will tell users they can only have one to one
        # relationships of agents and jobs to queues in a cluster)

    async def find_orphaned_jobs(self) -> List[Dict[str, Any]]:
        aiplatform = get_module(  # noqa: F811
            "google.cloud.aiplatform",
            "VertexRunner requires google.cloud.aiplatform to be installed",
        )
        jobset_label = self._construct_jobset_discoverability_label()
        self.logger.debug(f"Jobset label: {jobset_label}")
        list = event_loop_thread_exec(aiplatform.CustomJob.list)
        jobs = await list(
            filter=f"labels.{WANDB_VERTEX_JOBSET_DISCOVERABILITY_LABEL}={jobset_label}"
        )
        self.logger.debug(f"Found orphaned jobs: {jobs}")

        # TODO convert returned CustomJobs to dicts or Jobs
        raise NotImplementedError

    def label_job(self, project: LaunchProject) -> None:
        vertex_block = self._get_resource_block(project)
        if vertex_block is None:
            return
        jobset_label = self._construct_jobset_discoverability_label()
        spec = vertex_block.get("spec", {})
        labels = spec.get("labels", {})
        labels[WANDB_VERTEX_JOBSET_DISCOVERABILITY_LABEL] = jobset_label
        spec["labels"] = labels
        vertex_block["spec"] = spec
