"""Sweep tests."""
from unittest.mock import Mock, patch

import pytest
import wandb
from wandb.apis import internal, public
from wandb.errors import CommError
from wandb.sdk.launch.sweeps import SchedulerError, load_scheduler
from wandb.sdk.launch.sweeps.scheduler import (
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler

from .test_wandb_sweep import VALID_SWEEP_CONFIGS_MINIMAL


def test_sweep_scheduler_load():
    _scheduler = load_scheduler("sweep")
    assert _scheduler == SweepScheduler
    with pytest.raises(SchedulerError):
        load_scheduler("unknown")


@patch.multiple(Scheduler, __abstractmethods__=set())
@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_entity_project_sweep_id(user, relay_server, sweep_config):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        # Entity, project, and sweep should be everything you need to create a scheduler
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
        _ = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        # Bogus sweep id should result in error
        with pytest.raises(SchedulerError):
            _ = Scheduler(
                api, sweep_id="foo-sweep-id", entity=_entity, project=_project
            )


@patch.multiple(Scheduler, __abstractmethods__=set())
@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_base_scheduler_states(
    user, relay_server, sweep_config, monkeypatch
):

    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

        def mock_run_complete_scheduler(self, *args, **kwargs):
            self.state = SchedulerState.COMPLETED

        monkeypatch.setattr(
            "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
            mock_run_complete_scheduler,
        )

        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
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

        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        _scheduler.start()
        assert _scheduler.state == SchedulerState.STOPPED
        assert _scheduler.is_alive() is False

        def mock_run_raise_exception(*args, **kwargs):
            raise Exception("Generic exception")

        monkeypatch.setattr(
            "wandb.sdk.launch.sweeps.scheduler.Scheduler._run",
            mock_run_raise_exception,
        )

        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
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

        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        _scheduler.start()
        assert _scheduler.state == SchedulerState.FAILED
        assert _scheduler.is_alive() is False


@patch.multiple(Scheduler, __abstractmethods__=set())
@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_base_run_states(user, relay_server, sweep_config):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

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

        def mock_get_run_state(entity, project, run_id, *args, **kwargs):
            return mock_run_states[run_id][0]

        api.get_run_state = mock_get_run_state
        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        # Load up the runs into the Scheduler run dict
        for run_id in mock_run_states.keys():
            _scheduler._runs[run_id] = SweepRun(id=run_id, state=SimpleRunState.ALIVE)
        _scheduler._update_run_states()
        for run_id, _state in mock_run_states.items():
            if _state[1] == SimpleRunState.DEAD:
                # Dead runs should be removed from the run dict
                assert run_id not in _scheduler._runs.keys()
            else:
                assert _scheduler._runs[run_id].state == _state[1]

        # ---- If get_run_state errors out, runs should have the state UNKNOWN
        def mock_get_run_state_raise_exception(*args, **kwargs):
            raise CommError("Generic Exception")

        api.get_run_state = mock_get_run_state_raise_exception
        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        _scheduler._runs["foo_run_1"] = SweepRun(
            id="foo_run_1", state=SimpleRunState.ALIVE
        )
        _scheduler._runs["foo_run_2"] = SweepRun(
            id="foo_run_2", state=SimpleRunState.ALIVE
        )
        _scheduler._update_run_states()
        assert _scheduler._runs["foo_run_1"].state == SimpleRunState.UNKNOWN
        assert _scheduler._runs["foo_run_2"].state == SimpleRunState.UNKNOWN


@patch.multiple(Scheduler, __abstractmethods__=set())
@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_base_add_to_launch_queue(user, sweep_config, monkeypatch):
    api = internal.Api()

    _project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

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

    _scheduler = Scheduler(api, sweep_id=sweep_id, entity=user, project=_project)
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive() is False
    assert len(_scheduler._runs) == 1
    assert isinstance(_scheduler._runs["foo_run"].queued_run, public.QueuedRun)
    assert _scheduler._runs["foo_run"].state == SimpleRunState.DEAD


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
@pytest.mark.parametrize("num_workers", [1, 8])
def test_sweep_scheduler_sweeps_stop_agent_hearbeat(user, sweep_config, num_workers):
    api = internal.Api()

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "stop"}]

    api.agent_heartbeat = mock_agent_heartbeat

    _project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=user, project=_project, num_workers=num_workers
    )
    scheduler.start()
    assert scheduler.state == SchedulerState.STOPPED


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
@pytest.mark.parametrize("num_workers", [1, 8])
def test_sweep_scheduler_sweeps_invalid_agent_heartbeat(
    user, sweep_config, num_workers
):
    api = internal.Api()
    _project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "foo"}]

    api.agent_heartbeat = mock_agent_heartbeat

    with pytest.raises(SchedulerError) as e:
        _scheduler = SweepScheduler(
            api,
            sweep_id=sweep_id,
            entity=user,
            project=_project,
            num_workers=num_workers,
        )
        _scheduler.start()

    assert "unknown command" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() is False

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "run"}]  # No run_id should throw error

    api.agent_heartbeat = mock_agent_heartbeat

    with pytest.raises(SchedulerError) as e:
        _scheduler = SweepScheduler(
            api,
            sweep_id=sweep_id,
            entity=user,
            project=_project,
            num_workers=num_workers,
        )
        _scheduler.start()

    assert "missing run_id" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive() is False


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
@pytest.mark.parametrize("num_workers", [1, 8])
def test_sweep_scheduler_sweeps_run_and_heartbeat(
    user, sweep_config, num_workers, monkeypatch
):
    api = internal.Api()
    # Mock agent heartbeat stops after 10 heartbeats
    api.agent_heartbeat = Mock(
        side_effect=[
            [
                {
                    "type": "run",
                    "run_id": "mock-run-id-1",
                    "args": {"foo_arg": {"value": 1}},
                    "program": "train.py",
                }
            ]
        ]
        * 10
        + [[{"type": "stop"}]]
    )

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=public.QueuedRun)

    monkeypatch.setattr(
        "wandb.sdk.launch.launch_add._launch_add",
        mock_launch_add,
    )

    def mock_get_run_state(*args, **kwargs):
        return "runnning"

    api.get_run_state = mock_get_run_state

    _project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    _scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=user, project=_project, num_workers=num_workers
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    assert _scheduler._runs["mock-run-id-1"].state == SimpleRunState.DEAD
