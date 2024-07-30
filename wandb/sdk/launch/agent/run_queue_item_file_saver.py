"""Implementation of the run queue item file saver class."""

import os
import sys
from typing import List, Optional

import wandb

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

FileSubtypes = Literal["warning", "error"]


class RunQueueItemFileSaver:
    def __init__(
        self,
        agent_run: Optional["wandb.sdk.wandb_run.Run"],
        run_queue_item_id: str,
    ):
        self.run_queue_item_id = run_queue_item_id
        self.run = agent_run

    def save_contents(
        self, contents: str, fname: str, file_sub_type: FileSubtypes
    ) -> Optional[List[str]]:
        if not isinstance(self.run, wandb.sdk.wandb_run.Run):
            wandb.termwarn("Not saving file contents because agent has no run")
            return None
        root_dir = self.run._settings.files_dir
        saved_run_path = os.path.join(self.run_queue_item_id, file_sub_type, fname)
        local_path = os.path.join(root_dir, saved_run_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            f.write(contents)
        res = self.run.save(local_path, base_path=root_dir, policy="now")
        if isinstance(res, list):
            return [saved_run_path]
        else:
            wandb.termwarn(
                f"Failed to save files for run queue item: {self.run_queue_item_id}"
            )
            return None
