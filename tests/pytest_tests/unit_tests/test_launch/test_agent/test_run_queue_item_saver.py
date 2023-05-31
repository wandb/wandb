import os
from unittest.mock import MagicMock

from wandb.sdk.launch.agent.run_queue_item_file_saver import RunQueueItemFileSaver
from wandb.sdk.wandb_run import Run


def test_path_prefix():
    saver = RunQueueItemFileSaver(None, "test_run_queue_item_id")
    assert saver._path_prefix == os.path.join(saver.root_dir, "test_run_queue_item_id")


def test_no_run():
    saver = RunQueueItemFileSaver(None, "test_run_queue_item_id")
    assert saver.save_contents("contents", "fname", "error") is None


def test_run():
    run = MagicMock(spec=Run)
    run.save = MagicMock(return_value=["test_path"])
    saver = RunQueueItemFileSaver(run, "test_run_queue_item_id")
    assert saver.save_contents("contents", "fname", "error") == ["test_path"]
    run.save.assert_called_once_with(
        os.path.join(saver._path_prefix, "error", "fname"),
        base_path=saver.root_dir,
        policy="now",
    )
