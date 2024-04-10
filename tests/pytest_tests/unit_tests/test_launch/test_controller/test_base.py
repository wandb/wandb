from unittest.mock import AsyncMock, MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.base import BaseManager
from wandb.sdk.launch.agent2.jobset import Job
from wandb.sdk.launch.queue_driver.abstract import AbstractQueueDriver


class TestBaseManager(BaseManager):
    resource_type = "test"

    def __init__(self, config, jobset, logger, legacy, max_concurrency):
        self.queue_driver = AsyncMock(spec=AbstractQueueDriver)
        super().__init__(config, jobset, logger, legacy, max_concurrency)

    def label_job(self, project):
        project.mock_label_job()

    async def find_orphaned_jobs(self):
        pass


@pytest.fixture
def mocked_test_manager_reconile(controller_config, jobset) -> "TestBaseManager":
    mgr = TestBaseManager(controller_config, jobset, MagicMock(), MagicMock(), 1)
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
    assert mocked_test_manager_reconile.launch_item.call_count == 1


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
    await mocked_test_manager_reconile.reconcile()
    assert mocked_test_manager_reconile.release_item.called_once_with("not-test-id")
    assert mocked_test_manager_reconile.release_item.called_once_with("not-test-id")


@pytest.fixture
def mocked_test_manager(controller_config, jobset) -> "TestBaseManager":
    legacy = MagicMock()
    legacy.runner.run = AsyncMock()
    legacy.builder = AsyncMock()
    mgr = TestBaseManager(controller_config, jobset, MagicMock(), legacy, 1)
    return mgr


@pytest.mark.asyncio
async def test_cancel_job(mocked_test_manager):
    mock_abstract_run = AsyncMock()
    mock_abstract_run.get_status.return_value = "running"
    mocked_test_manager.active_runs = {"test-id": mock_abstract_run}
    await mocked_test_manager.cancel_job("test-id")
    assert mock_abstract_run.get_status.call_count == 1
    assert mock_abstract_run.cancel.call_count == 1


@pytest.mark.asyncio
async def test_release_item(mocked_test_manager):
    mocked_test_manager.active_runs = {"test-id": MagicMock()}
    await mocked_test_manager.release_item("test-id")
    assert mocked_test_manager.active_runs.get("test-id") is None


@pytest.mark.asyncio
async def test_pop_next_item(mocked_test_manager):
    await mocked_test_manager.pop_next_item()
    assert mocked_test_manager.queue_driver.pop_from_run_queue.call_count == 1


@pytest.mark.asyncio
async def test_launch_item(mocked_test_manager, mocker):
    job = Job(
        id="test-id",
        run_spec={
            "job": "test-entity/test-proj/job-ktest12abc:latest",
            "author": "test-entity",
            "entity": "test-entity",
            "project": "test-proj",
            "resource": "local-container",
            "overrides": {"args": [], "run_config": {}, "entry_point": []},
            "resource_args": {"local-container": {}},
            "_wandb_job_collection_id": "arti-id",
        },
        state="PENDING",
        priority=2,
        preemptible=False,
        can_preempt=True,
        created_at="2024-04-09T16:33:45",
        claimed_by=None,
    )
    mocked_test_manager.jobset.api.ack_jobset_item.return_value = {
        "ackRunQueueItem": {"id": "test-id"}
    }
    mock_launch_project = mocker.patch(
        "wandb.sdk.launch.agent2.controllers.base.LaunchProject", new_callable=MagicMock
    )
    mock_launch_project_instance = MagicMock()
    mock_launch_project_instance.docker_image = None
    mock_launch_project.from_spec.return_value = mock_launch_project_instance

    await mocked_test_manager.launch_item(job)
    assert mock_launch_project.from_spec.call_count == 1
    assert mock_launch_project_instance.fetch_and_validate_project.call_count == 1
    assert mocked_test_manager.legacy.job_tracker_factory.call_count == 1
    assert mocked_test_manager.jobset.api.ack_jobset_item.call_count == 1
    assert mocked_test_manager.legacy.builder.build_image.call_count == 1
    assert mock_launch_project_instance.mock_label_job.call_count == 1
    assert mocked_test_manager.legacy.runner.run.call_count == 1
    assert mocked_test_manager.active_runs.get("test-id") is not None
