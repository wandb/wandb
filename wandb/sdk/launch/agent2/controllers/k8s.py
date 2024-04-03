import asyncio
import json
import logging
from typing import Any, List

from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.abstract import AbstractRun

from ...queue_driver.standard_queue_driver import StandardQueueDriver
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet
from .base import BaseManager
from .util import parse_max_concurrency


async def k8s_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
) -> None:
    iter = 0
    max_concurrency = parse_max_concurrency(config, 1000)

    logger.debug(
        f"Starting kubernetes controller with max concurrency {max_concurrency}"
    )

    mgr = KubernetesManager(config, jobset, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(
            5
        )  # TODO(np): Ideally waits for job set or target resource events
        iter += 1

    return None


class KubernetesManager(BaseManager):
    """Maintains state for multiple Kubernetes jobs."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        self.queue_driver = StandardQueueDriver(jobset.api, jobset)
        super().__init__(config, jobset, logger, legacy, max_concurrency)
        # TODO: handle orphaned jobs in resource and assign to self

    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError
    
    async def cleanup_removed_jobs(self) -> None:
        raise NotImplementedError

    async def label_jobs(self) -> None:
        raise NotImplementedError
