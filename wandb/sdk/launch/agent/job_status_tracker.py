from dataclasses import dataclass
from typing import Optional

from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch._project_spec import LaunchProject

from ..runner.abstract import AbstractRun
from .run_queue_item_file_saver import RunQueueItemFileSaver


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

    def check_wandb_run_stopped(self, api: Api) -> bool:
        if (
            api._api is None
            or self.run_id is None
            or self.project is None
            or self.entity is None
        ):
            return False
        try:
            if api._api.check_stop_requested(self.project, self.entity, self.run_id):
                return True
        except CommError:
            pass
        return False
