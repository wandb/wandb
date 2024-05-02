from unittest.mock import MagicMock

import pytest
from wandb.errors import CommError
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.agent2.controllers.base import (
    BaseManager,
    RunWithTracker,
    check_run_called_init,
    check_run_exists_and_inited,
)
from wandb.sdk.launch.agent2.jobset import Job


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


class TestBaseManager(BaseManager):
    resource_type = "test"

    def __init__(self, config, jobset, logger, legacy, max_concurrency):
        self.queue_driver = AsyncMock()
        self.queue_driver.pop_from_run_queue = AsyncMock()
        self.queue_driver.pop_from_run_queue.return_value = Job(
            id="test-id",
            run_spec={},
            state="PENDING",
            priority=2,
            preemptible=False,
            can_preempt=True,
            created_at="2024-04-09T16:33:45",
            claimed_by=None,
        )
        super().__init__(config, jobset, logger, legacy, AsyncMock(), max_concurrency)

    def label_job(self, project):
        project.mock_label_job()

    async def find_orphaned_jobs(self):
        pass


@pytest.fixture
def mock_tracker():
    return JobAndRunStatusTracker(
        run_queue_item_id="test-rqi-id",
        queue="test-queue",
        saver=AsyncMock(),
        entity="entity",
        project="project",
        run_id="test-id",
        run=AsyncMock(),
    )


@pytest.fixture
def mock_run_with_tracker(mock_tracker):
    run = AsyncMock()
    return RunWithTracker(run, mock_tracker)


@pytest.fixture
def mocked_test_manager_reconile(controller_config, jobset) -> "TestBaseManager":
    mgr = TestBaseManager(controller_config, jobset, MagicMock(), MagicMock(), 1)
    mgr.launch_item = AsyncMock()
    mgr.pop_next_item = AsyncMock()
    mgr.pop_next_item.return_value = Job(
        id="test-id",
        run_spec={},
        state="PENDING",
        priority=2,
        preemptible=False,
        can_preempt=True,
        created_at="2024-04-09T16:33:45",
        claimed_by=None,
    )
    mgr.cancel_item = AsyncMock()
    mgr.release_item = AsyncMock()
    return mgr


@pytest.mark.asyncio
async def test_reconcile_launch_item(mocked_test_manager_reconile):
    await mocked_test_manager_reconile.reconcile()
    assert mocked_test_manager_reconile.pop_next_item.call_count == 1
    assert mocked_test_manager_reconile.cancel_item.call_count == 0
    assert mocked_test_manager_reconile.release_item.call_count == 0
    assert mocked_test_manager_reconile.jobset.api.get_jobset_by_spec.call_count == 1
    assert mocked_test_manager_reconile.launch_item.call_count == 1


@pytest.mark.asyncio
async def test_reconcile_max_concurrency(mocked_test_manager_reconile):
    max_concurrency = 0
    mocked_test_manager_reconile.max_concurrency = max_concurrency
    await mocked_test_manager_reconile.reconcile()
    assert mocked_test_manager_reconile.pop_next_item.call_count == 0
    assert mocked_test_manager_reconile.cancel_item.call_count == 0
    assert mocked_test_manager_reconile.release_item.call_count == 0
    assert mocked_test_manager_reconile.jobset.api.get_jobset_by_spec.call_count == 1


@pytest.mark.asyncio
async def test_reconcile_clear_unowned_item(
    mocked_test_manager_reconile, mock_run_with_tracker
):
    mocked_test_manager_reconile.max_concurrency = 0
    mock_run_with_tracker.run.get_status.return_value = "running"
    mocked_test_manager_reconile.active_runs = {"not-test-id": mock_run_with_tracker}
    await mocked_test_manager_reconile.reconcile()
    mocked_test_manager_reconile.cancel_item.assert_called_once_with("not-test-id")
    mocked_test_manager_reconile.release_item.assert_called_once_with("not-test-id")


@pytest.fixture
def mocked_test_manager(controller_config, jobset) -> "TestBaseManager":
    legacy = MagicMock()
    legacy.runner.run = AsyncMock()
    legacy.runner.run.return_value = "test-run-id"
    legacy.builder = AsyncMock()
    mgr = TestBaseManager(controller_config, jobset, MagicMock(), legacy, 1)
    return mgr


@pytest.mark.asyncio
async def test_cancel_item(mocked_test_manager, mock_run_with_tracker):
    mock_run_with_tracker.run.get_status.return_value = "running"
    mocked_test_manager.active_runs = {"test-id": mock_run_with_tracker}
    await mocked_test_manager.cancel_item("test-id")
    assert mock_run_with_tracker.run.get_status.call_count == 1
    assert mock_run_with_tracker.run.cancel.call_count == 1


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


@pytest.mark.parametrize(
    "called_init_value, run_id, status, check_init_count, failed_args",
    [
        (True, "test-id", "finished", 1, None),
        (
            False,
            "test-id",
            "stopped",
            1,
            (
                "test-rqi-id",
                "The submitted job failed to call wandb.init, exited with status: stopped",
                "run",
                None,
            ),
        ),
        (
            False,
            None,
            "finished",
            0,
            (
                "test-rqi-id",
                "The submitted job was finished without assigned project or run id",
                "agent",
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_finish_launched_run(
    mocked_test_manager,
    mock_run_with_tracker,
    mocker,
    called_init_value,
    run_id,
    status,
    check_init_count,
    failed_args,
):
    mock_api = AsyncMock()
    mock_fail_run_queue_item = (
        MagicMock()
    )  # TODO: when updating to use built-in AyncMock, switch to AsyncMock
    mock_api.fail_run_queue_item = mock_fail_run_queue_item
    mocked_test_manager.jobset.api = mock_api

    mock_run_called_init = AsyncMock()
    mock_run_called_init.return_value = (called_init_value, None)
    mocker.patch(
        "wandb.sdk.launch.agent2.controllers.base.check_run_called_init",
        mock_run_called_init,
    )

    mock_run_with_tracker.tracker.run_id = run_id

    await mocked_test_manager.finish_launched_run(mock_run_with_tracker, status)

    assert mock_run_called_init.call_count == check_init_count
    if failed_args is None:
        assert mock_api.fail_run_queue_item.call_count == 0
    else:
        assert mock_fail_run_queue_item.call_count == 1
        # index 0 because args
        assert mock_fail_run_queue_item.call_args[0] == failed_args


@pytest.mark.parametrize("use_tracker, phase", [(False, "agent"), (True, "run")])
@pytest.mark.asyncio
async def test_fail_run_with_exception(
    mocked_test_manager, mock_tracker, use_tracker, phase
):
    mock_api = MagicMock()
    mock_fail_run_queue_item = MagicMock()
    mock_api.fail_run_queue_item = mock_fail_run_queue_item
    mocked_test_manager.jobset.api = mock_api
    tracker = None
    if use_tracker:
        tracker = mock_tracker
        tracker.err_stage = "run"

    e = Exception("This is my exception")
    await mocked_test_manager.fail_run_with_exception("test-rqi-id", e, tracker)
    assert mock_api.fail_run_queue_item.call_count == 1
    assert mock_api.fail_run_queue_item.call_args[0][0] == "test-rqi-id"
    assert mock_api.fail_run_queue_item.call_args[0][1] == "This is my exception"
    assert mock_api.fail_run_queue_item.call_args[0][2] == phase


@pytest.mark.asyncio
async def test_fail_unsubmitted_run(mocked_test_manager):
    mock_api = MagicMock()
    mock_fail_run_queue_item = MagicMock()
    mock_api.fail_run_queue_item = mock_fail_run_queue_item
    mocked_test_manager.jobset.api = mock_api
    await mocked_test_manager.fail_unsubmitted_run("test-rqi-id")
    assert mock_api.fail_run_queue_item.call_count == 1
    assert mock_api.fail_run_queue_item.call_args[0][0] == "test-rqi-id"
    assert (
        mock_api.fail_run_queue_item.call_args[0][1]
        == "The job was not submitted successfully"
    )
    assert mock_api.fail_run_queue_item.call_args[0][2] == "agent"


@pytest.mark.asyncio
async def test_check_run_called_init(mocker):
    run = AsyncMock()
    count = 0

    async def mock_check_run_exists_and_inited(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return False
        return True

    mocker.patch(
        "wandb.sdk.launch.agent2.controllers.base.check_run_exists_and_inited",
        mock_check_run_exists_and_inited,
    )
    res, _ = await check_run_called_init(
        AsyncMock(), run, "test-entity", "test-proj", "test-id", "test-rqi-id"
    )
    assert res is True
    assert count == 2
    assert run.get_logs.call_count == 1


@pytest.mark.parametrize(
    "state, expected",
    [("running", True), ("pending", False)],
)
@pytest.mark.asyncio
async def test_check_run_exists_and_inited(state, expected):
    api = MagicMock()
    api.get_run_state.return_value = state
    res = await check_run_exists_and_inited(
        api, "test-entity", "test-proj", "test-id", "test-rqi-id"
    )
    assert res is expected


@pytest.mark.asyncio
async def test_check_run_exists_and_inited_exception():
    api = MagicMock()
    api.get_run_state.side_effect = CommError("This is my exception")
    res = await check_run_exists_and_inited(
        api, "test-entity", "test-proj", "test-id", "test-rqi-id"
    )
    assert res is False
