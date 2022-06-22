import pytest
import wandb
from unittest.mock import patch

from wandb.errors import SweepError
from wandb.sdk.launch.sweeps import load_scheduler
from wandb.sdk.launch.sweeps.scheduler import (
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler


def test_launch_sweeps_init_load_unknown_scheduler():
    with pytest.raises(ValueError):
        load_scheduler("unknown")


def test_launch_sweeps_init_load_tune_scheduler():
    from wandb.sdk.launch.sweeps.scheduler_tune import TuneScheduler

    _scheduler = load_scheduler("tune")
    assert (
        _scheduler == TuneScheduler
    ), f'load_scheduler("tune") should return Scheduler of type TuneScheduler'


def test_launch_sweeps_init_load_sweeps_scheduler():
    from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler

    _scheduler = load_scheduler("sweep")
    assert (
        _scheduler == SweepScheduler
    ), f'load_scheduler("sweep") should return Scheduler of type SweepScheduler'


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_base_scheduler_state(
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    # # Raise errors on bad entity/project
    # with pytest.raises(SweepError):
    #     Scheduler(api, entity="foo")
    # with pytest.raises(SweepError):
    #     Scheduler(api, project="foo")

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.RUNNING
    assert _scheduler.is_alive() == True
    _scheduler.exit()
    assert _scheduler.is_alive() == False
    assert _scheduler.state == SchedulerState.FAILED


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_base_scheduler_run_state(
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    # Mock api.get_run_state() to return crashed and running runs
    mock_run_states = {
        "run1": ("crashed", SimpleRunState.DEAD),
        "run2": ("failed", SimpleRunState.DEAD),
        "run3": ("killed", SimpleRunState.DEAD),
        "run4": ("finished", SimpleRunState.DEAD),
        "run5": ("running", SimpleRunState.ALIVE),
        "run6": ("pending", SimpleRunState.ALIVE),
        "run7": ("preempted", SimpleRunState.ALIVE),
        "run8": ("preempting", SimpleRunState.ALIVE),
    }

    def mock_get_run_state(entity, project, run_id):
        return mock_run_states[run_id][0]

    api.get_run_state = mock_get_run_state
    _scheduler = Scheduler(api, entity="foo", project="bar")
    for run_id in mock_run_states.keys():
        _scheduler._runs[run_id] = SweepRun(id=run_id, state=SimpleRunState.ALIVE)
    _scheduler._update_run_states()
    for run_id, _state in mock_run_states.items():
        assert _scheduler._runs[run_id].state == _state[1]


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_base_scheduler_add_to_launch_queue(
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def mock_push_to_run_queue(entity, project, run_id):
        pass

    api.push_to_run_queue = mock_push_to_run_queue


def test_launch_sweeps_sweeps_scheduler(
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def mock_agent_heartbeat(agent_id, metrics, run_states):
        pass

    def mock_sweep(sweep_id, specs, entity=None, project=None):
        if sweep_id == "404sweep":
            return False
        return True

    def mock_register_agent(host, sweep_id=None, project_name=None, entity=None):
        pass

    api.agent_heartbeat = mock_agent_heartbeat
    api.sweep = mock_sweep
    api.register_agent = mock_register_agent

    with pytest.raises(SweepError) as e:
        SweepScheduler(api, sweep_id="404sweep")
    assert "Could not find sweep" in str(e.value)
