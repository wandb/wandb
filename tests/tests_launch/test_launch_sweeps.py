from unittest.mock import Mock, patch

import pytest

import wandb
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
def test_launch_sweeps_scheduler_base_state(test_settings, monkeypatch):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    # # Raise errors on bad entity/project
    # with pytest.raises(SweepError):
    #     Scheduler(api, entity="foo")
    # with pytest.raises(SweepError):
    #     Scheduler(api, project="foo")

    def mock_run_complete_scheduler(self, *args, **kwargs):
        self.state = SchedulerState.COMPLETED

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_complete_scheduler,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive() == False

    def mock_run_raise_keyboard_interupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_raise_keyboard_interupt,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.CANCELLED
    assert _scheduler.is_alive() == False

    def mock_run_raise_exception(*args, **kwargs):
        raise Exception("Generic exception")

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_raise_exception,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    with pytest.raises(Exception) as e:
        _scheduler.start()
    assert "Generic exception" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() == False

    def mock_run_exit(self, *args, **kwargs):
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_exit,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() == False


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_launch_sweeps_scheduler_base_run_state(
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
def test_launch_sweeps_scheduler_base_add_to_launch_queue(test_settings, monkeypatch):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=wandb.apis.public.QueuedJob)

    monkeypatch.setattr(
        "wandb.sdk.launch.launch_add.launch_add",
        mock_launch_add,
    )

    def mock_run_add_to_launch_queue(self, *args, **kwargs):
        self._runs["foo_run"] = SweepRun(id="foo_run", state=SimpleRunState.ALIVE)
        self._add_to_launch_queue(run_id="foo_run")
        self.state = SchedulerState.COMPLETED
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_add_to_launch_queue,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive() == False
    assert len(_scheduler._runs) == 1
    assert isinstance(
        _scheduler._runs["foo_run"].launch_job, wandb.apis.public.QueuedJob
    )
    assert _scheduler._runs["foo_run"].state == SimpleRunState.DEAD


def test_launch_sweeps_scheduler_sweeps(test_settings, monkeypatch):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    api.agent_heartbeat = Mock(
        side_effect=[
            [
                {
                    "type": "run",
                    "run_id": "foo_run_1",
                    "args": {"foo_arg": {"value": 1}},
                    "program": "train.py",
                }
            ],
            [
                {
                    "type": "stop",
                    "run_id": "foo_run_1",
                }
            ],
            [
                {
                    "type": "resume",
                    "run_id": "foo_run_1",
                    "args": {"foo_arg": {"value": 1}},
                    "program": "train.py",
                }
            ],
            [
                {
                    "type": "exit",
                }
            ],
        ]
    )

    def mock_sweep(sweep_id, specs, entity=None, project=None):
        if sweep_id == "404sweep":
            return False
        return True

    def mock_register_agent(host, sweep_id=None, project_name=None, entity=None):
        return {"id": "foo_agent_pid"}

    api.sweep = mock_sweep
    api.register_agent = mock_register_agent

    def mock_add_to_launch_queue(self, *args, **kwargs):
        assert "entry_point" in kwargs
        assert kwargs["entry_point"] == [
            "python",
            "train.py",
            "--foo_arg=1",
        ]

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._add_to_launch_queue",
        mock_add_to_launch_queue,
    )

    with pytest.raises(SweepError) as e:
        SweepScheduler(api, sweep_id="404sweep")
    assert "Could not find sweep" in str(e.value)

    _scheduler = SweepScheduler(
        api,
        sweep_id="foo_sweep",
        # Faster sleeps for tests
        heartbeat_thread_sleep=1,
        heartbeat_queue_timeout=1,
        main_thread_sleep=1,
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() == True
    _scheduler.start()
    assert not _scheduler._heartbeat_thread.is_alive()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert len(_scheduler._runs) == 1
    assert _scheduler._runs["foo_run_1"].state == SimpleRunState.DEAD
