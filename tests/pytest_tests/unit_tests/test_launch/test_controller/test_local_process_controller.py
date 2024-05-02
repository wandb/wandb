from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.local_process import LocalProcessManager
from wandb.sdk.launch.agent2.jobset import Job
from wandb.sdk.launch.queue_driver.abstract import AbstractQueueDriver


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def local_process_manager(controller_config, jobset):
    return LocalProcessManager(
        controller_config, jobset, MagicMock(), MagicMock(), AsyncMock(), 1
    )


class TestLocalProcessManager(LocalProcessManager):
    def __init__(self, config, jobset, logger, legacy, queue, max_concurrency):
        self.queue_driver = AsyncMock(spec=AbstractQueueDriver)
        super().__init__(config, jobset, logger, legacy, queue, max_concurrency)


@pytest.fixture
def mocked_test_manager_reconile(
    controller_config, jobset
) -> "TestLocalProcessManager":
    mgr = TestLocalProcessManager(
        controller_config, jobset, MagicMock(), MagicMock(), AsyncMock(), 1
    )
    mgr.launch_item = AsyncMock()
    mgr.pop_next_item = AsyncMock()
    mgr.cancel_job = AsyncMock()
    mgr.release_item = AsyncMock()
    return mgr


@pytest.mark.asyncio
async def test_reconcile_launch_item(mocked_test_manager_reconile):
    await mocked_test_manager_reconile.reconcile()
    assert mocked_test_manager_reconile.pop_next_item.call_count == 1
    assert mocked_test_manager_reconile.cancel_job.call_count == 0
    assert mocked_test_manager_reconile.release_item.call_count == 0
    assert mocked_test_manager_reconile.jobset.api.get_jobset_by_spec.call_count == 1
    # because using fake AsyncMock can't assert call count, when local tests off of py37 can use call_count
    assert mocked_test_manager_reconile.launch_item.mock_call_count == 1


@pytest.mark.asyncio
async def test_reconcile_max_concurrency(mocked_test_manager_reconile):
    max_concurrency = 0
    mocked_test_manager_reconile.max_concurrency = max_concurrency
    await mocked_test_manager_reconile.reconcile()
    assert mocked_test_manager_reconile.pop_next_item.call_count == 0
    assert mocked_test_manager_reconile.cancel_job.call_count == 0
    assert mocked_test_manager_reconile.release_item.call_count == 0
    assert mocked_test_manager_reconile.jobset.api.get_jobset_by_spec.call_count == 1


@pytest.mark.asyncio
async def test_reconcile_clear_unowned_item(mocked_test_manager_reconile):
    mocked_test_manager_reconile.max_concurrency = 0
    mocked_test_manager_reconile.active_runs = {"not-test-id": MagicMock()}
    mocked_test_manager_reconile.release_item = MagicMock()
    await mocked_test_manager_reconile.reconcile()
    mocked_test_manager_reconile.release_item.assert_called_once_with("not-test-id")


@pytest.fixture
def mocked_test_manager(controller_config, jobset) -> "TestLocalProcessManager":
    legacy = MagicMock()
    legacy.runner.run = AsyncMock()
    legacy.runner.run.return_value = "test-run-id"
    mgr = LocalProcessManager(
        controller_config, jobset, MagicMock(), legacy, AsyncMock(), 1
    )
    return mgr


@pytest.mark.asyncio
async def test_launch_item(mocked_test_manager, mocker):
    job = Job(
        id="test-id",
        run_spec={
            "job": "test-entity/test-proj/job-ktest12abc:latest",
            "author": "test-entity",
            "entity": "test-entity",
            "project": "test-proj",
            "resource": "local-process",
            "overrides": {"args": [], "run_config": {}, "entry_point": []},
            "resource_args": {"local-process": {}},
            "_wandb_job_collection_id": "arti-id",
        },
        state="PENDING",
        priority=2,
        preemptible=False,
        can_preempt=True,
        created_at="2024-04-09T16:33:45",
        claimed_by=None,
    )
    mocked_test_manager.queue_driver.ack_run_queue_item = AsyncMock(return_value=True)
    mock_launch_project = mocker.patch(
        "wandb.sdk.launch.agent2.controllers.local_process.LaunchProject",
        new_callable=MagicMock,
    )
    mock_launch_project_instance = MagicMock()
    mock_launch_project_instance.docker_image = None
    mock_launch_project.from_spec.return_value = mock_launch_project_instance

    await mocked_test_manager.launch_item(job)
    assert mock_launch_project.from_spec.call_count == 1
    assert mock_launch_project_instance.fetch_and_validate_project.call_count == 1
    assert mocked_test_manager.legacy.job_tracker_factory.call_count == 1
    assert mocked_test_manager.queue_driver.ack_run_queue_item.call_count == 1
    assert mocked_test_manager.legacy.runner.run.call_count == 1
    assert mocked_test_manager.active_runs.get("test-id") is not None
