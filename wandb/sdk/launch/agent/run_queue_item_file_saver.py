"""Implementation of the agent file saver class"""

import os
import tempfile
from typing import List, Optional, Union

from wandb.sdk.lib import RunDisabled
from wandb.sdk.wandb_run import Run


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
        self, contents: str, fname: str, file_sub_type: str
    ) -> Optional[List[str]]:
        if not isinstance(self.run, Run):
            return None
        path = os.path.join(self._path_prefix, file_sub_type, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(contents)
        res = self.run.save(path, base_path=self.root_dir, policy="now")
        if isinstance(res, list):
            return res
        else:
            return None
