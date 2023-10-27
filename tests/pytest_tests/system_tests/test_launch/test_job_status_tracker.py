import base64
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker


@pytest.mark.asyncio
async def test_check_stop_run_not_exist(wandb_init):
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

    res = await job_tracker.check_wandb_run_stopped(api)
    assert not res
    run.finish()


@pytest.mark.asyncio
async def test_check_stop_run_exist_stopped(user, wandb_init):
    mock.patch("wandb.sdk.wandb_run.thread.interrupt_main", lambda x: None)
    job_tracker = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), MagicMock()
    )
    run = wandb_init(id="testrun", entity=user)
    print(run._entity)
    api = wandb.InternalApi()
    encoded_run_id = base64.standard_b64encode(
        f"Run:v1:testrun:{run._project}:{run._entity}".encode()
    ).decode("utf-8")
    mock_launch_project = MagicMock()
    mock_launch_project.target_entity = run._entity
    mock_launch_project.target_project = run._project
    mock_launch_project.run_id = run._run_id

    api_run = api.run_config(project=run._project, entity=run._entity, run=run._run_id)
    assert api_run

    job_tracker.update_run_info(mock_launch_project)
    assert api.stop_run(encoded_run_id)
    assert await job_tracker.check_wandb_run_stopped(api)
    run.finish()
