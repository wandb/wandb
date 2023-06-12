"""Implementation of the run queue item file saver class."""

import os
import sys
import tempfile
from typing import List, Optional, Union

import wandb
from wandb.sdk.lib import RunDisabled
from wandb.sdk.wandb_run import Run

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

FileSubtypes = Literal["warning", "error"]


class RunQueueItemFileSaver:
    def __init__(
        self, agent_run: Optional[Union[Run, RunDisabled]], run_queue_item_id: str
    ):
        self.run_queue_item_id = run_queue_item_id
        self.run = agent_run
        self.root_dir = tempfile.mkdtemp()

    @property
    def _path_prefix(self) -> str:
        return os.path.join(self.root_dir, self.run_queue_item_id)

    def save_contents(
        self, contents: str, fname: str, file_sub_type: FileSubtypes
    ) -> Optional[List[str]]:
        if not isinstance(self.run, Run):
            wandb.termwarn("Not saving file contents because agent has no run")
            return None
        path = os.path.join(self._path_prefix, file_sub_type, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(contents)
        res = self.run.save(path, base_path=self.root_dir, policy="now")
        if isinstance(res, list):
            return res
        else:
            wandb.termwarn(f"Failed to save files for run queue item: {self.run_queue_item_id}")
            return None
