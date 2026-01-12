from __future__ import annotations

import os
from unittest.mock import MagicMock

import wandb
from wandb.sdk.launch.agent.run_queue_item_file_saver import RunQueueItemFileSaver


def test_no_run():
    saver = RunQueueItemFileSaver(None, "test_run_queue_item_id")
    assert saver.save_contents("contents", "fname", "error") is None


def test_run():
    rqi_id = "test_run_queue_item_id"
    settings = MagicMock()
    settings.files_dir = "blah"
    run = MagicMock(spec=wandb.Run)
    run._settings = settings
    run.project = "test-project"
    run.entity = "test-entity"
    run.id = "test"
    run.save = MagicMock(return_value=["test_path"])
    saver = RunQueueItemFileSaver(run, rqi_id)
    assert saver.save_contents("contents", "fname", "error") == [
        os.path.join(rqi_id, "error", "fname")
    ]
    run.save.assert_called_once_with(
        os.path.join(settings.files_dir, rqi_id, "error", "fname"),
        base_path=saver.run._settings.files_dir,
        policy="now",
    )
