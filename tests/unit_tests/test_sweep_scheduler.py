"""Sweep tests."""
from unittest.mock import Mock, patch

import pytest
from wandb.apis import internal, public
from wandb.sdk.launch.sweeps import load_scheduler, SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler


def test_sweep_scheduler_load():
    _scheduler = load_scheduler("sweep")
    assert _scheduler == SweepScheduler
    with pytest.raises(SchedulerError):
        load_scheduler("unknown")


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_state(monkeypatch):
    api = internal.Api()

    def mock_run_complete_scheduler(self, *args, **kwargs):
        self.state = SchedulerState.COMPLETED

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_complete_scheduler,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive() is False

    def mock_run_raise_keyboard_interupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_raise_keyboard_interupt,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.STOPPED
    assert _scheduler.is_alive() is False

    def mock_run_raise_exception(*args, **kwargs):
        raise Exception("Generic exception")

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_raise_exception,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    with pytest.raises(Exception) as e:
        _scheduler.start()
    assert "Generic exception" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() is False

    def mock_run_exit(self, *args, **kwargs):
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
        mock_run_exit,
    )

    _scheduler = Scheduler(api, entity="foo", project="bar")
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() is False


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_run_state():
    api = internal.Api()
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

    def mock_get_run_state_raise_exception(*args, **kwargs):
        raise Exception("Generic Exception")

    api.get_run_state = mock_get_run_state_raise_exception
    _scheduler = Scheduler(api, entity="foo", project="bar")
    _scheduler._runs["foo_run_1"] = SweepRun(id="foo_run_1", state=SimpleRunState.ALIVE)
    _scheduler._runs["foo_run_2"] = SweepRun(id="foo_run_2", state=SimpleRunState.ALIVE)
    _scheduler._update_run_states()
    assert _scheduler._runs["foo_run_1"].state == SimpleRunState.UNKNOWN
    assert _scheduler._runs["foo_run_2"].state == SimpleRunState.UNKNOWN


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_add_to_launch_queue(monkeypatch):
    api = internal.Api()

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=public.QueuedRun)

    monkeypatch.setattr(
        "wandb.sdk.launch.launch_add._launch_add",
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
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive() is False
    assert len(_scheduler._runs) == 1
    assert isinstance(_scheduler._runs["foo_run"].queued_run, public.QueuedRun)
    assert _scheduler._runs["foo_run"].state == SimpleRunState.DEAD


def test_sweep_scheduler_sweeps(monkeypatch):
    api = internal.Api()

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

    def mock_sweep(self, sweep_id, *args, **kwargs):
        if sweep_id == "404sweep":
            return False
        return True

    monkeypatch.setattr("wandb.apis.internal.Api.sweep", mock_sweep)

    def mock_register_agent(*args, **kwargs):
        return {"id": "foo_agent_pid"}

    monkeypatch.setattr("wandb.apis.internal.Api.register_agent", mock_register_agent)

    # def mock_add_to_launch_queue(self, *args, **kwargs):
    #     assert "entry_point" in kwargs
    #     assert kwargs["entry_point"] == [
    #         "python",
    #         "train.py",
    #         "--foo_arg=1",
    #     ]

    # monkeypatch.setattr(
    #     "wandb.sdk.launch.sweeps.scheduler.Scheduler._add_to_launch_queue",
    #     mock_add_to_launch_queue,
    # )

    with pytest.raises(SchedulerError) as e:
        SweepScheduler(api, sweep_id="404sweep")
    assert "Could not find sweep" in str(e.value)

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=public.QueuedRun)

    monkeypatch.setattr(
        "wandb.sdk.launch.launch_add._launch_add",
        mock_launch_add,
    )

    def mock_get_run_state(*args, **kwargs):
        return "finished"

    monkeypatch.setattr("wandb.apis.internal.Api.get_run_state", mock_get_run_state)

    _scheduler = SweepScheduler(
        api,
        entity="mock-entity",
        project="mock-project",
        sweep_id="mock-sweep",
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    for _heartbeat_agent in _scheduler._heartbeat_agents:
        assert not _heartbeat_agent.thread.is_alive()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert len(_scheduler._runs) == 1
    assert _scheduler._runs["foo_run_1"].state == SimpleRunState.DEAD
