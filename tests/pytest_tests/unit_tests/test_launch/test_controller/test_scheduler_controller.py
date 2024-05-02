import asyncio
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.scheduler_controller import SchedulerController


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def scheduler_controller(controller_config, jobset, mocker):
    mock_scheduler_manager = AsyncMock()
    mock_scheduler_manager.active_runs = MagicMock()
    mock_scheduler_manager.active_runs.return_value = {}
    mock_scheduler_manager.launch_scheduler_item = AsyncMock()

    mock_queue = AsyncMock()
    mock_queue.get.return_value = MagicMock()
    scheduler_controller = SchedulerController(
        mock_scheduler_manager, 1, mock_queue, MagicMock()
    )
    return scheduler_controller


@pytest.mark.asyncio
async def test_scheduler_controller_poll(scheduler_controller):
    await scheduler_controller.poll()
    await asyncio.sleep(1)
    assert scheduler_controller._scheduler_jobs_queue.get.call_count == 1
    assert scheduler_controller._manager.launch_scheduler_item.call_count == 1


@pytest.mark.asyncio
async def test_scheduler_controller_poll_max_jobs(scheduler_controller, capsys):
    scheduler_controller._scheduler_jobs_queue.get.return_value = MagicMock()
    scheduler_controller._manager.active_runs = {1: MagicMock()}
    await scheduler_controller.poll()
    await asyncio.sleep(1)
    assert scheduler_controller._manager.launch_scheduler_item.call_count == 0
    captured = capsys.readouterr()
    assert "Agent already running the maximum number" in captured.err
