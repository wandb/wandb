import pytest
import wandb
from unittest.mock import patch

from wandb.errors import SweepError
from wandb.sdk.launch.sweeps import load_scheduler
from wandb.sdk.launch.sweeps.scheduler import Scheduler, SchedulerState, SimpleRunState
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
    live_mock_server,
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

    # State management
    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.exit()
    assert _scheduler.is_alive() == False
    assert _scheduler.state == SchedulerState.FAILED


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_base_scheduler_run_state(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    # Mock api.get_run_state() to return crashed and running runs


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_base_scheduler_add_to_launch_queue(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    # Verify adding to launch run queue


def test_launch_sweeps_sweeps_scheduler_happy_path(
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    SweepScheduler(api)

    # Mock the API?
    # self._api.agent_heartbeat?
    # self._api.sweep
    # self._api.register_agent

    # mock internal api upsert sweep to add json spec looks correct

    # test_launch_cli.py
    # test_cli.py

    # Skip mock server and just emulate api directly