import pytest
import wandb
from unittest.mock import patch

from wandb.errors import SweepError
from wandb.sdk.launch.sweeps import load_scheduler
from wandb.sdk.launch.sweeps.scheduler import Scheduler, SchedulerState


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
def test_launch_sweeps_base_scheduler(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    with pytest.raises(SweepError):
        Scheduler(api, entity="foo")
    with pytest.raises(SweepError):
        Scheduler(api, project="foo")
    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert (
        _scheduler.state == SchedulerState.PENDING
    ), f"Scheduler should be {SchedulerState.PENDING}"


def test_launch_sweeps_sweeps_scheduler_happy_path(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler

    SweepScheduler(api)
