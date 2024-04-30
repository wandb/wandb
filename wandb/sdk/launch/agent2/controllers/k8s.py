import asyncio
import logging
from typing import Any, Dict, List

from ..._project_spec import LaunchProject
from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet, JobWithQueue
from .base import BaseManager
from .util import parse_max_concurrency


async def k8s_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
    scheduler_queue: asyncio.Queue[JobWithQueue],
) -> None:
    iter = 0
    max_concurrency = parse_max_concurrency(config, 1000)

    logger.debug(
        f"Starting kubernetes controller with max concurrency {max_concurrency}"
    )

    mgr = KubernetesManager(
        config, jobset, logger, legacy, scheduler_queue, max_concurrency
    )

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1

    return None


class KubernetesManager(BaseManager):
    """Maintains state for multiple Kubernetes jobs."""

    resource_type = "kubernetes"

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        scheduler_queue: asyncio.Queue[JobWithQueue],
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
        raise NotImplementedError(
            "KubernetesManager.find_orphaned_jobs not implemented"
        )

    def label_job(self, project: LaunchProject) -> None:
        k8s_block = self._get_resource_block(project)
        if k8s_block is None:
            return
        metadata = k8s_block.setdefault("metadata", {})
        labels = metadata.setdefault("labels", {})

        # Always set or update the '_wandb-jobset' label
        labels["_wandb-jobset"] = "test-entity/test"
