import logging
from dataclasses import dataclass
from typing import Optional

from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch._project_spec import LaunchProject

from ..runner.abstract import AbstractRun
from ..utils import event_loop_thread_exec
from .run_queue_item_file_saver import RunQueueItemFileSaver

_logger = logging.getLogger(__name__)


WANDB_FINISHED_RUN_STATES = [
    "finished",
    "preempted",
    "killed",
    "stopped",
    "crashed",
    "failed",
]


@dataclass
class JobAndRunStatusTracker:
    run_queue_item_id: str
    queue: str
    saver: RunQueueItemFileSaver
    run_id: Optional[str] = None
    project: Optional[str] = None
    entity: Optional[str] = None
    run: Optional[AbstractRun] = None
    failed_to_start: bool = False
    completed_status: Optional[str] = None
    is_scheduler: bool = False
    err_stage: str = "agent"

    @property
    def job_completed(self) -> bool:
        return self.failed_to_start or self.completed_status is not None

    def update_run_info(self, launch_project: LaunchProject) -> None:
        self.run_id = launch_project.run_id
        self.project = launch_project.target_project
        self.entity = launch_project.target_entity

    def set_err_stage(self, stage: str) -> None:
        self.err_stage = stage

    async def check_wandb_run_finished_state(self, api: Api) -> bool:
        assert (
            self.run_id is not None
            and self.project is not None
            and self.entity is not None
        ), "Job tracker does not contain run info. Update with run info before checking run status"
        check_status = event_loop_thread_exec(api.api.get_run_state)
        try:
            state = await check_status(self.entity, self.project, self.run_id)
            if state in WANDB_FINISHED_RUN_STATES:
                return True
        # TODO: when runs are created when pushed to queue, return True if run is not found
        except CommError as e:
            _logger.error(f"CommError when checking wandb run status: {e}")
        return False

    async def check_wandb_run_stopped(self, api: Api) -> bool:
        assert (
            self.run_id is not None
            and self.project is not None
            and self.entity is not None
        ), "Job tracker does not contain run info. Update with run info before checking if run stopped"
        check_stop = event_loop_thread_exec(api.api.check_stop_requested)
        try:
            return bool(await check_stop(self.project, self.entity, self.run_id))
        except CommError as e:
            _logger.error(f"CommError when checking if wandb run stopped: {e}")
        return False
