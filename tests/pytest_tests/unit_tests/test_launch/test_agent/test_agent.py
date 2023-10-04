import threading
from unittest.mock import MagicMock

import pytest
from wandb.errors import CommError
from wandb.sdk.launch.agent.agent import JobAndRunStatusTracker, LaunchAgent
from wandb.sdk.launch.errors import LaunchDockerError, LaunchError


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

    mocker.status = MagicMock()
    mocker.status.state = "running"
    mocker.run = MagicMock()
    mocker.run.get_status = MagicMock(return_value=mocker.status)
    mocker.runner = MagicMock()
    mocker.runner.run = MagicMock(return_value=mocker.run)
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )


def test_loop_capture_stack_trace(mocker):
    _setup(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.run_job = MagicMock()
    agent.run_job.side_effect = [None, None, Exception("test exception")]
    agent.pop_from_queue = MagicMock(return_value=MagicMock())

    agent.loop()

    assert "Traceback (most recent call last):" in mocker.termerror.call_args[0][0]


def test_run_job_secure_mode(mocker):
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
            agent.run_job(job, "test-queue", mock_file_saver)


def _setup_requeue(mocker):
    _setup(mocker)
    mocker.event = MagicMock()
    mocker.event.is_set = MagicMock(return_value=True)

    mocker.status = MagicMock()
    mocker.status.state = "preempted"
    mocker.run = MagicMock()
    mocker.run.get_status = MagicMock(return_value=mocker.status)
    mocker.runner = MagicMock()
    mocker.runner.run = MagicMock(return_value=mocker.run)

    mocker.launch_add = MagicMock()

    mocker.patch("wandb.sdk.launch.agent.agent.threading", MagicMock())
    mocker.patch("multiprocessing.Event", mocker.event)
    mocker.patch("multiprocessing.pool.ThreadPool", MagicMock())
    mocker.project = MagicMock()
    mocker.patch(
        "wandb.sdk.launch.agent.agent.create_project_from_spec", mocker.project
    )
    mocker.project.return_value.target_entity = "test-entity"
    mocker.project.return_value.run_id = "test-run-id"

    mocker.patch("wandb.sdk.launch.agent.agent.fetch_and_validate_project", MagicMock())
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.builder_from_config",
        return_value=MagicMock(),
    )
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )

    mocker.api.fail_run_queue_item = MagicMock()
    mocker.patch("wandb.sdk.launch.agent.agent.launch_add", mocker.launch_add)


def test_requeue_on_preemption(mocker):
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
        mock_job["runQueueItemId"], "test-queue", MagicMock()
    )

    agent.thread_run_job(
        launch_spec=mock_launch_spec,
        job=mock_job,
        default_config={},
        api=mocker.api,
        job_tracker=job_tracker,
    )

    expected_config = {"run_id": "test-run-id", "_resume_count": 1}

    mocker.launch_add.assert_called_once_with(
        config=expected_config, project_queue="test-project", queue_name="test-queue"
    )


def test_team_entity_warning(mocker):
    _setup(mocker)
    mocker.api.entity_is_team = MagicMock(return_value=True)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    _ = LaunchAgent(api=mocker.api, config=mock_config)
    assert "Agent is running on team entity" in mocker.termwarn.call_args[0][0]


def test_non_team_entity_no_warning(mocker):
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
def test_max_scheduler_setup(mocker, num_schedulers):
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
def test_max_scheduler_setup_fail(mocker, num_schedulers):
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


def test_thread_finish_no_fail(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_info = MagicMock(return_value=lambda x: {"program": "blah"})
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
    assert not mock_saver.save_contents.called


def test_thread_finish_sweep_fail(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_info = MagicMock(return_value=None)
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once
    assert mock_saver.save_contents.called_once


def test_thread_finish_run_fail(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_info = MagicMock(side_effect=[CommError("failed")])
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once
    assert mock_saver.save_contents.called_once


def test_thread_finish_run_fail_start(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once
    assert mock_saver.save_contents.called_once


def test_thread_finish_run_fail_start_old_server(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent._gorilla_supports_fail_run_queue_items = False
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker("run_queue_item_id", "test-queue", mock_saver)
    job.run_id = "test_run_id"
    agent._jobs_lock = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
    assert not mock_saver.save_contents.called


def test_thread_finish_run_fail_different_entity(mocker):
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
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
    assert not mock_saver.save_contents.called


def test_agent_fails_sweep_state(mocker):
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
    job.completed_status = False
    job.run_id = "test-sweep-id"
    job.is_scheduler = True
    job.entity = "test-entity"
    job.project = "test-project"
    run = MagicMock()
    run.get_status.return_value.state = "failed"
    job.run = run

    # should detect failed scheduler, set sweep state to CANCELED
    out = agent._check_run_finished(job, {})
    assert job.completed_status == "failed"
    assert out, "True when status successfully updated"


def test_thread_finish_no_run(mocker):
    """Test that we fail RQI when the job exits 0 but there is no run."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_info.return_value = None
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
    agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    assert mocker.api.fail_run_queue_item.call_args[0][0] == "run_queue_item_id"
    assert (
        mocker.api.fail_run_queue_item.call_args[0][1]
        == "The submitted job exited successfully but failed to call wandb.init"
    )


def test_thread_failed_no_run(mocker):
    """Test that we fail RQI when the job exits non-zero but there is no run."""
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_info.return_value = None
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
    agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    assert mocker.api.fail_run_queue_item.call_args[0][0] == "run_queue_item_id"
    assert (
        mocker.api.fail_run_queue_item.call_args[0][1]
        == "The submitted run was not successfully started"
    )


@pytest.mark.timeout(90)
def test_thread_finish_run_info_backoff(mocker):
    """Test that our retry + backoff logic for run info works.

    This test should take at least 60 seconds.
    """
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }
    mocker.api.get_run_info.side_effect = CommError("failed")
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    mock_saver = MagicMock()
    job = JobAndRunStatusTracker(
        "run_queue_item_id", "test-queue", mock_saver, run=MagicMock()
    )
    job.run_id = "test_run_id"
    job.project = MagicMock()
    job.completed_status = "failed"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    agent.finish_thread_id("thread_1")
    assert mocker.api.fail_run_queue_item.called
    # we should be able to call get_run_info  at 0, 1, 3, 7, 15, 31, 63 seconds
    assert mocker.api.get_run_info.call_count == 7


@pytest.mark.parametrize(
    "exception",
    [
        LaunchDockerError("launch docker error"),
        LaunchError("launch error"),
        Exception("exception"),
        None,
    ],
)
def test_thread_run_job_calls_finish_thread_id(mocker, exception):
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
        return None

    agent._thread_run_job = mock_thread_run_job
    mock_finish_thread_id = MagicMock()
    agent.finish_thread_id = mock_finish_thread_id
    agent.thread_run_job({}, {}, {}, MagicMock(), job)

    mock_finish_thread_id.assert_called_once_with(
        threading.current_thread().ident, exception
    )


def test_inner_thread_run_job(mocker):
    _setup(mocker)
    mocker.patch("wandb.sdk.launch.agent.agent.MAX_WAIT_RUN_STOPPED", new=0)
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
    cancel = MagicMock()
    mocker.run.cancel = cancel

    def side_effect_func():
        job.completed_status = True

    cancel.side_effect = side_effect_func

    agent._thread_run_job(
        mock_spec,
        {"runQueueItemId": "blah"},
        {},
        mocker.api,
        threading.current_thread().ident,
        job,
    )
    cancel.assert_called_once()


def test_get_job_and_queue(mocker):
    _setup(mocker)
    mock_config = {
        # "entity": "test-entity",
        # "project": "test-project",
        "queues": ["queue-1", "queue-2", "queue-3"]
    }
    mock_job = {"test-key": "test-value"}
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent.pop_from_queue = MagicMock(return_value=mock_job)

    job_and_queue = agent.get_job_and_queue()

    assert job_and_queue is not None
    assert job_and_queue.job == mock_job
    assert job_and_queue.queue == "queue-1"
    assert agent._queues == ["queue-2", "queue-3", "queue-1"]
