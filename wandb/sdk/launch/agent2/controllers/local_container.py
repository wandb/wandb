import asyncio
import logging
from typing import Any, List

from ...queue_driver import passthrough
from ...utils import MAX_CONCURRENCY
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet
from .base import BaseManager


async def local_container_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    legacy: LegacyResources,
):
    # disable job set loop because we are going to use the passthrough queue driver
    # to drive the launch controller here
    jobset.stop_sync_loop()

    iter = 0
    max_concurrency = config["jobset_metadata"][MAX_CONCURRENCY]

    if max_concurrency is None or max_concurrency == "auto":
        # detect # of cpus available
        import multiprocessing

        max_concurrency = max(1, multiprocessing.cpu_count() - 1)
        logger.debug(
            f"Detecting max_concurrency as {max_concurrency} (based on # of CPUs available)"
        )

    logger.debug(
        f"Starting local container controller with max concurrency {max_concurrency}"
    )

    mgr = LocalContainerManager(config, jobset, logger, legacy, max_concurrency)

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(5)
        iter += 1


class LocalContainerManager(BaseManager):
    """Maintains state for multiple docker containers."""

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        max_concurrency: int,
    ):
        self.queue_driver = passthrough.PassthroughQueueDriver(
            api=jobset.api,
            queue_name=config["jobset_spec"].name,
            entity=config["jobset_spec"].entity_name,
            project=config["jobset_spec"].project_name,
            agent_id=config["agent_id"],
        )

        super().__init__(config, jobset, logger, legacy, max_concurrency)

        # TODO: handle orphaned runs and assign to self (blocked on accurately knowing the agent that launched these runs has been killed)

    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError

    async def cleanup_removed_jobs(self) -> None:
        raise NotImplementedError

    async def label_jobs(self) -> None:
        raise NotImplementedError
