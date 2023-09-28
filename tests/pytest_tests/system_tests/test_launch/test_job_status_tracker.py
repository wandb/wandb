import threading
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import CommError
from wandb.sdk.launch.agent.agent import JobAndRunStatusTracker, LaunchAgent
from wandb.sdk.launch.errors import LaunchDockerError, LaunchError


def test_check_stop_run_not_exist(wandb_init):
    """Should handle the raised CommError and return False when a run does not exist"""
    job_tracker = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), MagicMock()
    )
    run = wandb_init(id="testrun")
    api = wandb.InternalApi()
    mock_launch_project = MagicMock()
    mock_launch_project.target_entity = run._entity
    mock_launch_project.target_project = run._project
    mock_launch_project.run_id = run._run_id + "a"
    job_tracker.update_run_info(mock_launch_project)

    res = job_tracker.check_wandb_run_stopped(api)
    assert not res


def test_check_stop_run_exist_stopped(wandb_init):
    """Should handle the raised CommError and return False when a run does not exist"""
    job_tracker = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), MagicMock()
    )
    run = wandb_init(id="testrun")
    api = wandb.InternalApi(
        default_settings={"project": run._project, "entity": run._entity}
    )
    mock_launch_project = MagicMock()
    mock_launch_project.target_entity = run._entity
    mock_launch_project.target_project = run._project
    mock_launch_project.run_id = run._run_id
    job_tracker.update_run_info(mock_launch_project)

    assert api.stop_run(run._run_id)

    res = job_tracker.check_wandb_run_stopped(api)
    assert res
