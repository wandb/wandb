from unittest.mock import MagicMock

import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker


def test_check_stop_run_not_exist(wandb_init):
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
    run.finish()


def test_check_stop_run_exist_stopped(wandb_init):
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
    run.finish()
