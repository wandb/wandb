import asyncio
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.scheduler_controller import (
    SchedulerController,
    SchedulerManager,
)
from wandb.sdk.launch.agent2.jobset import Job, JobWithQueue


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def scheduler_controller(controller_config, jobset, mocker):
    mock_scheduler_manager = AsyncMock()
    mock_scheduler_manager.active_runs = MagicMock()
    mock_scheduler_manager.active_runs.return_value = {}

    mock_queue = AsyncMock()
    mock_queue.get.return_value = MagicMock()
    scheduler_controller = SchedulerController(
        mock_scheduler_manager, 1, mock_queue, MagicMock()
    )
    return scheduler_controller


@pytest.mark.asyncio
async def test_scheduler_controller_poll(scheduler_controller):
    scheduler_controller._manager.launch_scheduler_item = AsyncMock()
    await scheduler_controller.poll()
    await asyncio.sleep(1)
    assert scheduler_controller._scheduler_jobs_queue.get.call_count == 1
    assert scheduler_controller._manager.launch_scheduler_item.call_count == 1


@pytest.mark.asyncio
async def test_scheduler_controller_poll_max_jobs(scheduler_controller, capsys):
    scheduler_controller._scheduler_jobs_queue.get.return_value = MagicMock()
    scheduler_controller._manager.active_runs = {1: MagicMock()}
    scheduler_controller._manager.launch_scheduler_item = AsyncMock()
    await scheduler_controller.poll()
    await asyncio.sleep(1)
    assert scheduler_controller._manager.launch_scheduler_item.call_count == 0
    captured = capsys.readouterr()
    assert "Agent already running the maximum number" in captured.err


@pytest.mark.asyncio
async def test_scheduler_manager_ack_run_queue_item():
    scheduler_manager = SchedulerManager(
        MagicMock(), 1, MagicMock(), AsyncMock(), MagicMock()
    )
    await scheduler_manager.ack_run_queue_item("test", "asd")
    assert scheduler_manager._api.ack_run_queue_item.call_count == 1


@pytest.mark.asyncio
async def test_scheduler_manager_launch_scheduler_item():
    scheduler_manager = SchedulerManager(
        MagicMock(), 1, MagicMock(), AsyncMock(), MagicMock()
    )
    scheduler_manager._populate_project = MagicMock()
    scheduler_manager._launch_job = AsyncMock(return_value="run-id")
    ret = await scheduler_manager.launch_scheduler_item(MagicMock())
    assert scheduler_manager._populate_project.call_count == 1
    assert scheduler_manager._launch_job.call_count == 1
    assert ret == "run-id"


@pytest.mark.asyncio
def test_scheduler_manager_populate_project():
    scheduler_manager = SchedulerManager(
        MagicMock(), 1, MagicMock(), AsyncMock(), MagicMock()
    )
    item = JobWithQueue(
        job=Job(
            id="test-id",
            run_spec={
                "job": "test-job",
                "project": "test-project",
                "entity": "test-entity",
            },
            priority=0,
            preemptible=False,
            can_preempt=False,
            created_at="2024-04-09T16:33:45",
            claimed_by="testagebnt",
            state="PENDING",
        ),
        queue="test-queue",
        entity="test-entity",
    )
    project = scheduler_manager._populate_project(item)
    assert project.queue_name == "test-queue"
    assert project.queue_entity == "test-entity"
    assert project.run_queue_item_id == "test-id"
