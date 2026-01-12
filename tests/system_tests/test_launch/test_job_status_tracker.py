from __future__ import annotations

import base64
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker


@pytest.mark.asyncio
async def test_check_stop_run_not_exist(user):
    job_tracker = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), MagicMock()
    )
    run = wandb.init(id="testrun")
    api = wandb.InternalApi()
    mock_launch_project = MagicMock()
    mock_launch_project.target_entity = run.entity
    mock_launch_project.target_project = run.project
    mock_launch_project.run_id = run.id + "a"
    job_tracker.update_run_info(mock_launch_project)

    res = await job_tracker.check_wandb_run_stopped(api)
    assert not res
    run.finish()


@pytest.mark.asyncio
async def test_check_stop_run_exist_stopped(user):
    mock.patch("wandb.sdk.wandb_run.thread.interrupt_main", lambda x: None)
    job_tracker = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), MagicMock()
    )
    run = wandb.init(id="testrun", entity=user)
    api = wandb.InternalApi()
    encoded_run_id = base64.standard_b64encode(
        f"Run:v1:testrun:{run.project}:{run.entity}".encode()
    ).decode("utf-8")
    mock_launch_project = MagicMock()
    mock_launch_project.target_entity = run.entity
    mock_launch_project.target_project = run.project
    mock_launch_project.run_id = run.id

    api_run = api.run_config(project=run.project, entity=run.entity, run=run.id)
    assert api_run

    job_tracker.update_run_info(mock_launch_project)
    assert api.stop_run(encoded_run_id)
    assert await job_tracker.check_wandb_run_stopped(api)
    run.finish()
