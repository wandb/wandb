import asyncio
import logging
from typing import Any, List

from ..._project_spec import LaunchProject
from ...queue_driver import passthrough
from ...utils import MAX_CONCURRENCY
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import JobSet, JobWithQueue
from .base import WANDB_JOBSET_DISCOVERABILITY_LABEL, BaseManager


async def local_container_controller(
    config: LaunchControllerConfig,
    jobset: JobSet,
    logger: logging.Logger,
    shutdown_event: asyncio.Event,
    scheduler_queue: "asyncio.Queue[JobWithQueue]",
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

    mgr = LocalContainerManager(
        config, jobset, logger, legacy, scheduler_queue, max_concurrency
    )

    while not shutdown_event.is_set():
        await mgr.reconcile()
        await asyncio.sleep(5)
        iter += 1


class LocalContainerManager(BaseManager):
    """Maintains state for multiple docker containers."""

    resource_type = "local-container"

    def __init__(
        self,
        config: LaunchControllerConfig,
        jobset: JobSet,
        logger: logging.Logger,
        legacy: LegacyResources,
        scheduler_queue: "asyncio.Queue[JobWithQueue]",
        max_concurrency: int,
    ):
        self.queue_driver = passthrough.PassthroughQueueDriver(
            api=jobset.api,
            queue_name=config["jobset_spec"].name,
            entity=config["jobset_spec"].entity_name,
            project=config["jobset_spec"].project_name,
            agent_id=config["agent_id"],
        )

        super().__init__(
            config, jobset, logger, legacy, scheduler_queue, max_concurrency
        )
        # TODO: handle orphaned runs and assign to self (blocked on accurately knowing the agent that launched these runs has been killed)

    async def find_orphaned_jobs(self) -> List[Any]:
        raise NotImplementedError(
            "LocalContainerManager.find_orphaned_jobs not implemented"
        )

    def label_job(self, project: LaunchProject) -> None:
        resource_block = self._get_resource_block(project)
        if resource_block is None:
            return
        jobset_label = self._construct_jobset_discoverability_label()
        label_value = f"{WANDB_JOBSET_DISCOVERABILITY_LABEL}={jobset_label}"

        self._update_or_set_labels(resource_block, label_value)

    def _update_or_set_labels(self, resource_block, label_value):
        label_key = (
            "l" if "l" in resource_block or "label" not in resource_block else "label"
        )
        if isinstance(resource_block.get(label_key), list):
            resource_block[label_key].append(label_value)
        else:
            if resource_block.get(label_key) is not None:
                resource_block[label_key] = [resource_block[label_key], label_value]
            else:
                resource_block[label_key] = [label_value]
