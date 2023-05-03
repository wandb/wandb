from unittest.mock import MagicMock

import pytest
from wandb.errors import CommError
from wandb.sdk.launch.agent.agent import JobAndRunStatus, LaunchAgent
from wandb.sdk.launch.utils import LaunchError


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
    for job, error in zip(jobs, errors):
        with pytest.raises(ValueError, match=error):
            agent.run_job(job)


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
    elif type(num_schedulers) is str:
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
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called


def test_thread_finish_sweep_fail(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_info = MagicMock(return_value=None)
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once


def test_thread_finish_run_fail(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    mocker.api.get_run_info = MagicMock(side_effect=[CommError("failed")])
    agent = LaunchAgent(api=mocker.api, config=mock_config)
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    job.project = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once


def test_thread_finish_run_fail_start(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert mocker.api.fail_run_queue_item.called_once


def test_thread_finish_run_fail_start_old_server(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    agent._gorilla_supports_fail_run_queue_items = False
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    agent._jobs_lock = MagicMock()
    agent._jobs = {"thread_1": job}
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called


def test_thread_finish_run_fail_different_entity(mocker):
    _setup_thread_finish(mocker)
    mock_config = {
        "entity": "test-entity",
        "project": "test-project",
    }

    agent = LaunchAgent(api=mocker.api, config=mock_config)
    job = JobAndRunStatus("run_queue_item_id")
    job.run_id = "test_run_id"
    job.project = "test-project"
    job.entity = "other-entity"
    agent._jobs = {"thread_1": job}
    agent._jobs_lock = MagicMock()
    agent.finish_thread_id("thread_1")
    assert len(agent._jobs) == 0
    assert not mocker.api.fail_run_queue_item.called
