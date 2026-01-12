from __future__ import annotations

import asyncio
import platform
import threading
from unittest.mock import MagicMock

import pytest
from wandb.errors import CommError
from wandb.sdk.launch.agent.agent import (
    InternalAgentLogger,
    JobAndRunStatusTracker,
    LaunchAgent,
)
from wandb.sdk.launch.errors import LaunchDockerError, LaunchError
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT, LOG_PREFIX


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def clean_agent():
    LaunchAgent._instance = None
    yield
    LaunchAgent._instance = None


def _setup(mocker):
    mocker.api = MagicMock()
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.fail_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    mocker.termlog = MagicMock()
    mocker.termwarn = MagicMock()
    mocker.termerror = MagicMock()
    mocker.wandb_init = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mocker.patch("wandb.termerror", mocker.termerror)
    mocker.patch("wandb.init", mocker.wandb_init)
    mocker.logger = MagicMock()
    mocker.patch("wandb.sdk.launch.agent.agent._logger", mocker.logger)

    mocker.status = MagicMock()
    mocker.status.state = "running"
    mocker.run = MagicMock()

    # async def _mock_get_status(*args, **kwargs):
    #     return mocker.status

    mocker.run.get_status = AsyncMock(return_value=mocker.status)
    mocker.runner = MagicMock()

    async def _mock_runner_run(*args, **kwargs):
        return mocker.run

    mocker.runner.run = _mock_runner_run
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )


@pytest.mark.asyncio
async def test_loop_capture_stack_trace(mocker, clean_agent):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.run_job = AsyncMock()
    agent.run_job.side_effect = [None, None, Exception("test exception")]
    agent.pop_from_queue = AsyncMock(return_value=MagicMock())

    await agent.loop()

    assert "Traceback (most recent call last):" in mocker.termerror.call_args[0][0]


@pytest.mark.asyncio
async def test_run_job_secure_mode(mocker, clean_agent):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "secure_mode": True,
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)

    jobs = [
        {
            "runSpec": {
                "resource_args": {
                    "kubernetes": {"spec": {"template": {"spec": {"hostPID": True}}}}
                }
            }
        },
        {
            "runSpec": {
                "resource_args": {
                    "kubernetes": {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [{}, {"command": ["some", "code"]}]
                                }
                            }
                        }
                    }
                }
            }
        },
        {"runSpec": {"overrides": {"entry_point": ["some", "code"]}}},
    ]
    errors = [
        'This agent is configured to lock "hostPID" in pod spec but the job specification attempts to override it.',
        'This agent is configured to lock "command" in container spec but the job specification attempts to override it.',
        'This agent is configured to lock the "entrypoint" override but the job specification attempts to override it.',
    ]
    mock_file_saver = MagicMock()
    for job, error in zip(jobs, errors):
        with pytest.raises(ValueError, match=error):
            await agent.run_job(job, "test-queue", mock_file_saver)


def _setup_requeue(mocker):
    _setup(mocker)
    mocker.event = MagicMock()
    mocker.event.is_set = MagicMock(return_value=True)

    mocker.status = MagicMock()
    mocker.status.state = "preempted"
    mocker.run = MagicMock()

    _mock_get_status = AsyncMock(return_value=mocker.status)
    mocker.run.get_status = _mock_get_status
    mocker.runner = MagicMock()

    mocker.runner.run = AsyncMock(return_value=mocker.run)

    mocker.launch_add = MagicMock()

    mocker.project = MagicMock()
    mocker.project.target_entity = "test-entity"
    mocker.project.run_id = "test-run-id"

    mocker.patch(
        "wandb.sdk.launch.agent.agent.LaunchProject.from_spec",
        return_value=mocker.project,
    )
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.builder_from_config",
        return_value=None,
    )
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )

    mocker.api.fail_run_queue_item = MagicMock()
    mocker.patch("wandb.sdk.launch.agent.agent.launch_add", mocker.launch_add)


@pytest.mark.asyncio
async def test_requeue_on_preemption(mocker, clean_agent):
    _setup_requeue(mocker)

    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mock_job = {
        "runQueueItemId": "test-id",
    }
    mock_launch_spec = {}

    agent = LaunchAgent(api=mocker.api, config=mock_config)

    job_tracker = JobAndRunStatusTracker(
        mock_job["runQueueItemId"], "test-queue", MagicMock(), entity="test-entity"
    )
    assert job_tracker.entity == "test-entity"

    await agent.task_run_job(
        launch_spec=mock_launch_spec,
        job=mock_job,
        default_config={},
        api=mocker.api,
        job_tracker=job_tracker,
    )

    expected_config = {"run_id": "test-run-id", "_resume_count": 1}

    mocker.launch_add.assert_called_once_with(
        config=expected_config,
        project_queue=LAUNCH_DEFAULT_PROJECT,
        queue_name="test-queue",
    )


def test_team_entity_warning(mocker, clean_agent):
    _setup(mocker)
    mocker.api.entity_is_team = MagicMock(return_value=True)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    _ = LaunchAgent(api=mocker.api, config=mock_config)
    assert "Agent is running on team entity" in mocker.termwarn.call_args[0][0]


def test_non_team_entity_no_warning(mocker, clean_agent):
    _setup(mocker)
    mocker.api.entity_is_team = MagicMock(return_value=False)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    _ = LaunchAgent(api=mocker.api, config=mock_config)
    assert not mocker.termwarn.call_args


@pytest.mark.parametrize(
    "num_schedulers",
    [0, -1, 1000000, "8", None],
)
def test_max_scheduler_setup(mocker, num_schedulers, clean_agent):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "max_schedulers": num_schedulers,
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)

    if num_schedulers is None:
        num_schedulers = 1  # default for none
    elif num_schedulers == -1:
        num_schedulers = float("inf")
    elif isinstance(num_schedulers, str):
        num_schedulers = int(num_schedulers)

    assert agent._max_schedulers == num_schedulers


@pytest.mark.parametrize(
    "num_schedulers",
    [-29, "weird"],
)
def test_max_scheduler_setup_fail(mocker, num_schedulers, clean_agent):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "max_schedulers": num_schedulers,
    }
    with pytest.raises(LaunchError):
        LaunchAgent(api=mocker.api, config=mock_config)


def _setup_thread_finish(mocker):
    mocker.api = MagicMock()
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.fail_run_queue_item = MagicMock()
    mocker.termlog = MagicMock()
    mocker.termerror = MagicMock()
    mocker.wandb_init = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termerror", mocker.termerror)
    mocker.patch("wandb.init", mocker.wandb_init)


@pytest.mark.asyncio
async def test_thread_finish_no_fail(mocker, clean_agent):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_state = MagicMock(return_value=lambda x: True)
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
    assert not mock_saver.save_contents.called


@pytest.mark.asyncio
async def test_thread_finish_sweep_fail(mocker, clean_agent):
    """Test thread finished with 0 exit status, but sweep didn't init."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_state = MagicMock(return_value="pending")
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 1)
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    run = MagicMock()

    async def mock_get_logs():
        return "logs"

    run.get_logs = mock_get_logs
    job.run = run
    agent._jobs = {"thread_1": job}
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    mocker.api.fail_run_queue_item.assert_called_once()
    mock_saver.save_contents.assert_called_once()


@pytest.mark.asyncio
async def test_thread_finish_run_fail(mocker, clean_agent):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_state.side_effect = CommError("failed")
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 1)
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    run = MagicMock()

    async def mock_get_logs():
        return "logs"

    run.get_logs = mock_get_logs
    job.run = run
    agent._jobs = {"thread_1": job}
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    mocker.api.fail_run_queue_item.assert_called_once()
    mock_saver.save_contents.assert_called_once()


@pytest.mark.asyncio
async def test_thread_finish_run_fail_start(mocker, clean_agent):
    """Tests that if a run does not exist, the run queue item is failed."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_state.side_effect = CommError("failed")
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 1)

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = "test-project"
    run = MagicMock()

    async def mock_get_logs():
        return "logs"

    run.get_logs = mock_get_logs
    job.run = run
    job.run_queue_item_id = "asdasd"

    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    mocker.api.fail_run_queue_item.assert_called_once()
    mock_saver.save_contents.assert_called_once()


@pytest.mark.asyncio
async def test_thread_finish_run_fail_start_old_server(mocker, clean_agent):
    """Tests that if a run does not exist, the run queue item is not failed for old servers."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_state.side_effect = CommError("failed")
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 1)

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent._gorilla_supports_fail_run_queue_items = False
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.run_queue_item_id = "asdasd"
    job.project = "test-project"
    run = MagicMock()

    async def mock_get_logs():
        return "logs"

    run.get_logs = mock_get_logs
    job.run = run
    agent._jobs_lock = MagicMock()
    agent._jobs = {"thread_1": job}
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    mocker.api.fail_run_queue_item.assert_not_called()


@pytest.mark.asyncio
async def test_thread_finish_run_fail_different_entity(mocker, clean_agent):
    """Tests that no check is made if the agent entity does not match."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = "test-project"
    job.entity = "other-entity"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    await agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
    assert not mock_saver.save_contents.called


@pytest.mark.asyncio
async def test_agent_fails_sweep_state(mocker, clean_agent):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    def mock_set_sweep_state(sweep, entity, project, state):
        assert entity == "test-entity"
        assert project == "test-project"
        assert sweep == "test-sweep-id"
        assert state == "CANCELED"

    mocker.api.set_sweep_state = mock_set_sweep_state

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "_queue", mock_saver)
    job.completed_status = "failed"
    job.run_id = "test-sweep-id"
    job.is_scheduler = True
    job.entity = "test-entity"
    job.project = "test-project"
    run = MagicMock()
    run.get_status.return_value.state = "failed"
    job.run = run

    # should detect failed scheduler, set sweep state to CANCELED
    out = await agent._check_run_finished(job, {})
    assert job.completed_status == "failed"
    assert out, "True when status successfully updated"


@pytest.mark.skipif(platform.system() == "Windows", reason="fails on windows")
@pytest.mark.asyncio
async def test_thread_finish_no_run(mocker, clean_agent):
    """Test that we fail RQI when the job exits 0 but there is no run."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_state.side_effect = CommError("failed")
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=MagicMock()
    )
    job.run_id = "test_run_id"
    job.project = MagicMock()
    job.completed_status = "finished"
    agent._jobs = {"thread_1": job}
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 0)
    await agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    assert mocker.api.fail_run_queue_item.call_args[0][0] == "run_queue_item_id"
    assert (
        mocker.api.fail_run_queue_item.call_args[0][1]
        == "The submitted job exited successfully but failed to call wandb.init"
    )


@pytest.mark.skipif(platform.system() == "Windows", reason="fails on windows")
@pytest.mark.asyncio
async def test_thread_failed_no_run(mocker, clean_agent):
    """Test that we fail RQI when the job exits non-zero but there is no run."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_state.side_effect = CommError("failed")
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=MagicMock()
    )
    job.run_id = "test_run_id"
    job.project = MagicMock()
    job.completed_status = "failed"
    agent._jobs = {"thread_1": job}
    mocker.patch("wandb.sdk.launch.agent.agent.RUN_INFO_GRACE_PERIOD", 0)
    await agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    assert mocker.api.fail_run_queue_item.call_args[0][0] == "run_queue_item_id"
    assert (
        mocker.api.fail_run_queue_item.call_args[0][1]
        == "The submitted run was not successfully started"
    )


@pytest.mark.timeout(90)
@pytest.mark.asyncio
async def test_thread_finish_run_info_backoff(mocker, clean_agent):
    """Test that our retry + backoff logic for run info works.

    This test should take at least 60 seconds.
    """
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.patch("asyncio.sleep", AsyncMock())

    mocker.api.get_run_state.side_effect = CommError("failed")
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    submitted_run = MagicMock()
    submitted_run.get_logs = AsyncMock(return_value="test logs")
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=submitted_run
    )
    job.run_id = "test_run_id"
    job.project = MagicMock()
    job.completed_status = "failed"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    await agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    # we should be able to call get_run_state  at 0, 1, 3, 7, 15, 31, 63 seconds
    assert mocker.api.get_run_state.call_count == 7


@pytest.mark.parametrize(
    "exception",
    [
        LaunchDockerError("launch docker error"),
        LaunchError("launch error"),
        Exception("exception"),
        None,
    ],
)
@pytest.mark.asyncio
async def test_thread_run_job_calls_finish_thread_id(mocker, exception, clean_agent):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=MagicMock()
    )
    agent = LaunchAgent(api=mocker.api, config=mock_config)

    def mock_thread_run_job(*args, **kwargs):
        if exception is not None:
            raise exception
        return asyncio.sleep(0)

    agent._task_run_job = mock_thread_run_job
    mock_finish_thread_id = AsyncMock()
    agent.finish_thread_id = mock_finish_thread_id
    await agent.task_run_job({}, dict(runQueueItemId="rqi-xxxx"), {}, MagicMock(), job)

    mock_finish_thread_id.assert_called_once_with("rqi-xxxx", exception)


@pytest.mark.asyncio
async def test_inner_thread_run_job(mocker, clean_agent):
    _setup(mocker)
    mocker.patch("wandb.sdk.launch.agent.agent.DEFAULT_STOPPED_RUN_TIMEOUT", new=0)
    mocker.patch("wandb.sdk.launch.agent.agent.AGENT_POLLING_INTERVAL", new=0)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=MagicMock()
    )
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_spec = {
        "docker": {"docker_image": "blah-blah:latest"},
        "entity": "user",
        "project": "test",
    }

    mocker.api.check_stop_requested = True

    def _side_effect(*args, **kwargs):
        job.completed_status = True

    mocker.run.cancel = AsyncMock(side_effect=_side_effect)

    await agent._task_run_job(
        mock_spec,
        {"runQueueItemId": "blah"},
        {},
        mocker.api,
        threading.current_thread().ident,
        job,
    )
    mocker.run.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_raise_warnings(mocker, clean_agent):
    _setup(mocker)
    mocker.status = MagicMock()
    mocker.status.state = "preempted"
    mocker.status.messages = ["Test message"]
    mocker.run = MagicMock()
    _mock_get_status = AsyncMock(return_value=mocker.status)
    mocker.run.get_status = _mock_get_status
    mocker.runner = MagicMock()
    mocker.runner.run = AsyncMock(return_value=mocker.run)
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )

    mocker.patch("wandb.sdk.launch.agent.agent.DEFAULT_STOPPED_RUN_TIMEOUT", new=0)
    mocker.patch("wandb.sdk.launch.agent.agent.AGENT_POLLING_INTERVAL", new=0)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", MagicMock(), run=mocker.run
    )
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_spec = {
        "docker": {"docker_image": "blah-blah:latest"},
        "entity": "user",
        "project": "test",
    }

    await agent._task_run_job(
        mock_spec,
        {"runQueueItemId": "blah"},
        {},
        mocker.api,
        threading.current_thread().ident,
        job,
    )
    assert agent._known_warnings == ["Test message"]
    mocker.api.update_run_queue_item_warning.assert_called_once_with(
        "run_queue_item_id", "Test message", "Kubernetes", []
    )


@pytest.mark.asyncio
async def test_get_job_and_queue(mocker):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
        "queues": ["queue-1", "queue-2", "queue-3"],
    }
    mock_job = {"test-key": "test-value"}
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.pop_from_queue = AsyncMock(return_value=mock_job)

    job_and_queue = await agent.get_job_and_queue()

    assert job_and_queue is not None
    assert job_and_queue.job == mock_job
    assert job_and_queue.queue == "queue-1"
    assert agent._queues == ["queue-2", "queue-3", "queue-1"]


def test_get_agent_name(mocker, clean_agent):
    with pytest.raises(LaunchError):
        LaunchAgent.name()
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    LaunchAgent(api=mocker.api, config=mock_config)

    assert LaunchAgent.name() == "test-name"


def test_agent_logger(mocker):
    _setup(mocker)

    # Normal logger
    logger = InternalAgentLogger()
    logger.error("test 1")
    mocker.termerror.assert_not_called()
    mocker.logger.error.assert_called_once_with(f"{LOG_PREFIX}test 1")
    logger.warn("test 2")
    mocker.termwarn.assert_not_called()
    mocker.logger.warning.assert_called_once_with(f"{LOG_PREFIX}test 2")
    logger.info("test 3")
    mocker.termlog.assert_not_called()
    mocker.logger.info.assert_called_once_with(f"{LOG_PREFIX}test 3")
    logger.debug("test 4")
    mocker.termlog.assert_not_called()
    mocker.logger.debug.assert_called_once_with(f"{LOG_PREFIX}test 4")

    # Verbose logger
    logger = InternalAgentLogger(verbosity=2)
    logger.error("test 5")
    mocker.termerror.assert_called_with(f"{LOG_PREFIX}test 5")
    mocker.logger.error.assert_called_with(f"{LOG_PREFIX}test 5")
    logger.warn("test 6")
    mocker.termwarn.assert_called_with(f"{LOG_PREFIX}test 6")
    mocker.logger.warning.assert_called_with(f"{LOG_PREFIX}test 6")
    logger.info("test 7")
    mocker.termlog.assert_called_with(f"{LOG_PREFIX}test 7")
    mocker.logger.info.assert_called_with(f"{LOG_PREFIX}test 7")
    logger.debug("test 8")
    mocker.termlog.assert_called_with(f"{LOG_PREFIX}test 8")
    mocker.logger.debug.assert_called_with(f"{LOG_PREFIX}test 8")


def test_agent_inf_jobs(mocker):
    config = {
        "entity": "mock_server_entity",
        "project": "test_project",
        "queues": ["default"],
        "max_jobs": -1,
    }
    mocker.patch(
        "wandb.sdk.launch.agent.agent.LaunchAgent._init_agent_run", lambda x: None
    )
    agent = LaunchAgent(MagicMock(), config)
    assert agent._max_jobs == float("inf")


@pytest.mark.asyncio
async def test_run_job_api_key_redaction(mocker):
    """Test that API keys are redacted when logging job details in run_job method."""
    _setup(mocker)
    mock_term_log = mocker.termlog

    job_data = {
        "runQueueItemId": "test-queue-item-id",
        "runSpec": {
            "_wandb_api_key": "test_api_key",
            "docker": {"docker_image": "test-image"},
            "project": "test-project",
        },
    }

    agent = LaunchAgent(
        api=mocker.api, config={"entity": "test-entity", "project": "test-project"}
    )
    agent.update_status = AsyncMock()
    agent.task_run_job = AsyncMock()

    await agent.run_job(job_data, "test-queue", MagicMock())

    log_message = mock_term_log.call_args[0][0]

    assert "<redacted>" in log_message
    assert "test_api_key" not in log_message
