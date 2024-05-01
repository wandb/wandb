import asyncio
import json
import logging
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner.abstract import AbstractRun, Status
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.lib.hashutil import b64_to_hex_id, md5_string

from ...agent.agent import RUN_INFO_GRACE_PERIOD
from ...queue_driver.abstract import AbstractQueueDriver
from ...utils import event_loop_thread_exec
from ..controller import LaunchControllerConfig, LegacyResources
from ..jobset import Job, JobSet, JobWithQueue

WANDB_JOBSET_DISCOVERABILITY_LABEL = "_wandb-jobset"


def _is_scheduler_job(run_spec: Dict[str, Any]) -> bool:
    """Determine whether a job/runSpec is a sweep scheduler."""
    if run_spec.get("uri") != Scheduler.PLACEHOLDER_URI:
        return False

    if run_spec.get("resource") == "local-process":
        # Any job pushed to a run queue that has a scheduler uri is
        # allowed to use local-process
        if run_spec.get("job"):
            return True

        # If a scheduler is local-process and run through CLI, also
        #    confirm command is in format: [wandb scheduler <sweep>]
        cmd = run_spec.get("overrides", {}).get("entry_point", [])
        if len(cmd) < 3:
            return False

        if cmd[:2] != ["wandb", "scheduler"]:
            return False

    return True


@dataclass
class RunWithTracker:
    run: AbstractRun
    tracker: JobAndRunStatusTracker


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
        scheduler_queue: "asyncio.Queue[JobWithQueue]",
        max_concurrency: int,
    ):
        self.config = config
        self.jobset = jobset
        self.logger = logger
        self.legacy = legacy
        self.max_concurrency = max_concurrency
        self._scheduler_queue = scheduler_queue

        self.id = config["jobset_spec"].name
        self.active_runs: Dict[str, RunWithTracker] = {}
        if self.queue_driver is None:
            raise LaunchError(
                "queue_driver is not set, set queue driver in subclass constructor"
            )

    async def reconcile(self) -> None:
        """Reconcile the current set of active runs with the jobset.

        Performs the following checks to ensure the controller is in a consistent state with the jobset:
        - Determining the items in the current job set
        - Determining items owned by the current controller
        - Checking whether there is capacity for the controller to own more items
        - Leasing and launching the next item if there is capacity
        - Clearing items from the active runs that are no longer in the job set
        - Checking the status of active runs and releasing them if they are no longer running
        """
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
                print("ITEM", item)
                await self.cancel_item(item)
                await self.release_item(item)

        # now check for active runs that are no longer
        # actually running
        for item_id, run_with_tracker in list(self.active_runs.items()):
            run = run_with_tracker.run
            status = await run.get_status()
            if status not in ["running", "pending"]:
                # run is no longer running
                await self.finish_launched_run(run_with_tracker, status)
                await self.release_item(item_id)

    async def pop_next_item(self) -> Optional[Job]:
        """Pop the next item from the run queue."""
        assert self.queue_driver is not None
        next_item = await self.queue_driver.pop_from_run_queue()
        self.logger.info(f"Leased item: {next_item}")
        return next_item

    async def launch_item(self, job: Job) -> Optional[str]:
        """Launch a new job on the resource."""
        self.logger.info(f"Launching item: {job}")
        assert self.queue_driver is not None
        try:
            project = LaunchProject.from_spec(job.run_spec, self.legacy.api)
            run_id = project.run_id
            project.queue_name = self.config["jobset_spec"].name
            project.queue_entity = self.config["jobset_spec"].entity_name
            job_tracker = self.legacy.job_tracker_factory(
                run_id, self.config["jobset_spec"].name
            )
            job_tracker.update_run_info(project)
        except Exception as e:
            self.logger.error(
                f"Error parsing run spec, and initializing job tracker {job.id}: {e}"
            )
            await self.fail_run_with_exception(job.id, e)
            return None
        try:
            project.run_queue_item_id = job.id
            project.fetch_and_validate_project()

            if (
                _is_scheduler_job(job.run_spec)
                and job.run_spec.get("resource") == "local-process"
            ):
                self.logger.info(
                    f"Received scheduler job sending to sweep scheduler manager: {job.id}"
                )
                job_with_queue = JobWithQueue(
                    job, project.queue_name, project.queue_entity
                )
                await self._scheduler_queue.put(job_with_queue)
                # no need to handle anymore, sent to another controller
                return None

            ack_result = await self.jobset.ack_job(job.id, run_id)
            self.logger.info(f"Acked item: {json.dumps(ack_result, indent=2)}")
            if not ack_result:
                self.logger.error(f"Failed to ack item: {job.id}")
                return None
            image_uri = None
            if not project.docker_image:
                entrypoint = project.get_job_entry_point()
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
                self.logger.error(f"Failed to start run for item {job.id}")
                await self.fail_unsubmitted_run(job.id)
                return None
        except Exception as e:
            self.logger.error(f"Error launching item {job.id}: {e}")
            await self.fail_run_with_exception(job.id, e, job_tracker)
            return None
        self.active_runs[job.id] = RunWithTracker(run, job_tracker)

        self.logger.info(f"Inside launch_item, project.run_id = {run_id}")
        return project.run_id

    async def release_item(self, item_id: str) -> None:
        """Clear the active run for the given item."""
        self.logger.info(f"Releasing item: {item_id}")
        del self.active_runs[item_id]

    def _construct_jobset_discoverability_label(self) -> str:
        return b64_to_hex_id(
            md5_string(
                f"{self.config['jobset_spec'].entity_name}/{self.config['jobset_spec'].name}"
            )
        )

    async def cancel_item(self, item: str) -> None:
        """Cancel a running job currently managed by the controller."""
        run = self.active_runs[item].run
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
        """Find existing jobs on the resource tagged with discoverability label that are not actively being managed by the controller and return them."""
        raise NotImplementedError

    @abstractmethod
    def label_job(self, project: LaunchProject) -> None:
        """Updates the resource block of the project with the discoverability label."""
        raise NotImplementedError

    async def finish_launched_run(
        self, run_with_tracker: RunWithTracker, status: Status
    ) -> None:
        """Check the status of a submitted run in a terminal state and mark the item failed if the run did not call wandb.init."""
        run = run_with_tracker.run
        tracker = run_with_tracker.tracker
        item_id = tracker.run_queue_item_id
        entity = tracker.entity
        project = tracker.project
        run_id = tracker.run_id

        if entity is None or project is None or run_id is None:
            self.logger.error(
                f"called finish_thread_id on thread whose tracker has no project or run id. RunQueueItemID: {item_id}"
            )

            fail_run_queue_item = event_loop_thread_exec(
                self.jobset.api.fail_run_queue_item
            )
            await fail_run_queue_item(
                item_id,
                "The submitted job was finished without assigned project or run id",
                "agent",
            )

            return
        run_called_init, logs = await check_run_called_init(
            self.jobset.api, run, entity, project, run_id, item_id
        )

        if not run_called_init:
            fnames = None
            if logs:
                fnames = tracker.saver.save_contents(logs, "error.log", "error")

            fail_run_queue_item = event_loop_thread_exec(
                self.jobset.api.fail_run_queue_item
            )
            await fail_run_queue_item(
                item_id,
                f"The submitted job failed to call wandb.init, exited with status: {status}",
                "run",
                fnames,
            )

    async def fail_run_with_exception(
        self,
        item_id: str,
        exception: Exception,
        tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> None:
        """Mark a run queue item failed with an exception."""
        tb_str = traceback.format_exception(
            type(exception), value=exception, tb=exception.__traceback__
        )
        fnames = None
        phase = None
        if tracker is not None:
            phase = tracker.err_stage
            fnames = tracker.saver.save_contents("".join(tb_str), "error.log", "error")
        else:
            phase = "agent"

        fail_run_queue_item = event_loop_thread_exec(
            self.jobset.api.fail_run_queue_item
        )
        await fail_run_queue_item(item_id, str(exception), phase, fnames)

        return

    async def fail_unsubmitted_run(self, item_id: str) -> None:
        """Mark a run queue item that failed to be submitted as failed."""
        fail_run_queue_item = event_loop_thread_exec(
            self.jobset.api.fail_run_queue_item
        )
        await fail_run_queue_item(
            item_id,
            "The job was not submitted successfully",
            "agent",
        )
        return


async def check_run_called_init(
    api: Api,
    run: AbstractRun,
    entity: str,
    project: str,
    run_id: str,
    run_queue_item_id: str,
) -> Tuple[bool, Optional[str]]:
    called_init = False
    # We do some weird stuff here getting run info to check for a
    # created in run in W&B.
    #
    # We retry for 60 seconds with an exponential backoff in case
    # upsert run is taking a while.
    logs = None
    interval = 1
    while True:
        called_init = await check_run_exists_and_inited(
            api,
            entity,
            project,
            run_id,
            run_queue_item_id,
        )
        if called_init or interval > RUN_INFO_GRACE_PERIOD:
            break
        if not called_init:
            # Fetch the logs now if we don't get run info on the
            # first try, in case the logs are cleaned from the runner
            # environment (e.g. k8s) during the run info grace period.
            if interval == 1:
                logs = await run.get_logs()
            await asyncio.sleep(interval)
            interval *= 2
    return called_init, logs


async def check_run_exists_and_inited(
    api: Api, entity: str, project: str, run_id: str, rqi_id: str
) -> bool:
    """Checks the state of the run to ensure it has been inited. Note this will not behave well with resuming."""
    # Checks the _wandb key in the run config for the run queue item id. If it exists, the
    # submitted run definitely called init. Falls back to checking state of run.
    # TODO: handle resuming runs

    # Sweep runs exist but are in pending state, normal launch runs won't exist
    # so will raise a CommError.
    try:
        get_run_state = event_loop_thread_exec(api.get_run_state)
        run_state = await get_run_state(entity, project, run_id)
        if run_state.lower() != "pending":
            return True
    except CommError:
        wandb.termwarn(
            f"Run {entity}/{project}/{run_id} with rqi id: {rqi_id} did not have associated run"
        )
    return False
