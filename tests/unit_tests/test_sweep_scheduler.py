"""Sweep tests."""
from unittest.mock import Mock, patch

import pytest
import wandb
from wandb.apis import internal, public
from wandb.sdk.launch.sweeps import load_scheduler, SchedulerError
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
            raise Exception("Generic Exception")

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
def test_sweep_scheduler_base_add_to_launch_queue(
    user, relay_server, sweep_config, monkeypatch
):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

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

        _scheduler = Scheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)
        assert _scheduler.state == SchedulerState.PENDING
        assert _scheduler.is_alive() is True
        _scheduler.start()
        assert _scheduler.state == SchedulerState.COMPLETED
        assert _scheduler.is_alive() is False
        assert len(_scheduler._runs) == 1
        assert isinstance(_scheduler._runs["foo_run"].queued_run, public.QueuedRun)
        assert _scheduler._runs["foo_run"].state == SimpleRunState.DEAD


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_sweeps_add_to_launch_queue(user, relay_server, sweep_config, monkeypatch):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_sweeps_single_threading(user, relay_server, sweep_config, monkeypatch):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

    _scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )

    def mock_get_run_state(*args, **kwargs):
        return "finished"

    api.get_run_state = mock_get_run_state


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_scheduler_sweeps_multi_threading(user, relay_server, sweep_config, monkeypatch):
    with relay_server():
        _entity = user
        _project = "test-project"
        api = internal.Api()
        sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

    _scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=4
    )


    # api.agent_heartbeat = Mock(
    #     side_effect=[
    #         [
    #             {
    #                 "type": "run",
    #                 "run_id": "foo_run_1",
    #                 "args": {"foo_arg": {"value": 1}},
    #                 "program": "train.py",
    #             }
    #         ],
    #         [
    #             {
    #                 "type": "stop",
    #                 "run_id": "foo_run_1",
    #             }
    #         ],
    #         [
    #             {
    #                 "type": "resume",
    #                 "run_id": "foo_run_1",
    #                 "args": {"foo_arg": {"value": 1}},
    #                 "program": "train.py",
    #             }
    #         ],
    #         [
    #             {
    #                 "type": "exit",
    #             }
    #         ],
    #     ]
    # )

    # def mock_register_agent(*args, **kwargs):
    #     return {"id": "foo_agent_pid"}

    # monkeypatch.setattr("wandb.apis.internal.Api.register_agent", mock_register_agent)

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

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=public.QueuedRun)

    monkeypatch.setattr(
        "wandb.sdk.launch.launch_add._launch_add",
        mock_launch_add,
    )

    def mock_get_run_state(*args, **kwargs):
        return "finished"

    api.get_run_state = mock_get_run_state

    _scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive() is True
    _scheduler.start()
    # for _heartbeat_agent in _scheduler._workers:
    #     assert not _heartbeat_agent.thread.is_alive()
    assert _scheduler.state == SchedulerState.COMPLETED
    # assert len(_scheduler._runs) == 1
    # assert _scheduler._runs["foo_run_1"].state == SimpleRunState.DEAD
