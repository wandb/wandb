"""Sweep tests."""

import asyncio
from unittest.mock import Mock, patch

import pytest
import wandb
from wandb.apis import internal, public
from wandb.errors import CommError
from wandb.sdk.launch.sweeps import SchedulerError, SweepNotFoundError, load_scheduler
from wandb.sdk.launch.sweeps.scheduler import (
    RunState,
    Scheduler,
    SchedulerState,
    SweepRun,
)
from wandb.sdk.launch.sweeps.scheduler_sweep import SweepScheduler
from wandb.sdk.launch.sweeps.utils import construct_scheduler_args

from .test_wandb_sweep import SWEEP_CONFIG_RANDOM


def test_sweep_scheduler_load():
    _scheduler = load_scheduler("wandb")
    assert _scheduler == SweepScheduler
    with pytest.raises(SchedulerError):
        load_scheduler("unknown")


def _patch_wandb_run(monkeypatch, config=None):
    if not config:
        config = {"launch": {"overrides": {"run_config": {}}}}
    mocked_run = Mock(["finish", "id"])
    mocked_run.config = config
    mocked_run.id = "sweep-scheduler"
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._init_wandb_run",
        lambda _x: mocked_run,
    )


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_entity_project_sweep_id(
    user,
    monkeypatch,
):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    _entity = user
    _project = "test-project"
    api = internal.Api()
    # Entity, project, and sweep should be everything you need to create a scheduler
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    _ = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    # Bogus sweep id should result in error
    with pytest.raises(SchedulerError):
        _ = Scheduler(
            api,
            sweep_id="foo-sweep-id",
            entity=_entity,
            project=_project,
        )


def test_sweep_scheduler_start_failed(user, monkeypatch):
    _patch_wandb_run(monkeypatch)
    sweep_config = SWEEP_CONFIG_RANDOM
    _entity = user
    _project = "test-project"
    api = internal.Api()
    # Entity, project, and sweep should be everything you need to create a scheduler
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

    api.stop_run = lambda run_id: True
    scheduler = SweepScheduler(api, sweep_id=sweep_id, entity=_entity, project=_project)

    # also test stop run
    assert scheduler._stop_run("nonexistent-run") is False
    scheduler._runs["existing-run-no-queued"] = SweepRun(
        id="existing-run-no-queued", state=RunState.RUNNING, worker_id=0
    )
    assert scheduler._stop_run("existing-run-no-queued") is False
    scheduler._runs["existing-run-dead"] = SweepRun(
        id="existing-run-dead",
        state=RunState.CRASHED,
        worker_id=1,
        queued_run=Mock(spec=public.QueuedRun),
    )
    assert scheduler._stop_run("existing-run-dead") is True
    scheduler._runs["existing-run"] = SweepRun(
        id="existing-run",
        worker_id=2,
        queued_run=Mock(spec=public.QueuedRun),
    )
    assert scheduler._stop_run("existing-run")

    scheduler.state = SchedulerState.CANCELLED
    scheduler.start()
    # should not be able to start a cancelled scheduler
    assert scheduler.state == SchedulerState.CANCELLED


def test_sweep_scheduler_runcap(user, monkeypatch):
    launch_config = {"launch": {}}
    _patch_wandb_run(monkeypatch, launch_config)
    sweep_config = SWEEP_CONFIG_RANDOM  # 3 total runs
    sweep_config["run_cap"] = 2
    _entity = user
    _project = "test-project"

    def mock_launch_add(*args, **kwargs):
        mock = Mock(spec=public.QueuedRun)
        mock.args = Mock(return_value=args)
        return mock

    monkeypatch.setattr(
        "wandb.sdk.launch._launch_add._launch_add",
        mock_launch_add,
    )

    def mock_run_add_to_launch_queue(self, *args, **kwargs):
        self._runs["foo_run"] = SweepRun(
            id="foo_run",
            state=RunState.PENDING,
            worker_id=0,
            args={"foo": {"value": 1}},
        )
        self._add_to_launch_queue(self._runs["foo_run"])
        self.state = SchedulerState.COMPLETED
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._get_next_sweep_run",
        mock_run_add_to_launch_queue,
    )

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    # Entity, project, and sweep should be everything you need to create a scheduler
    api = internal.Api()
    api.get_run_state = mock_get_run_state
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    scheduler = SweepScheduler(
        api,
        sweep_id=sweep_id,
        entity=_entity,
        project=_project,
        image_uri="fake-image:latest",
        queue="queue",
        num_workers=1,
    )

    assert scheduler.at_runcap is False
    scheduler.start()
    assert scheduler.at_runcap
    assert scheduler._num_runs_launched == 2


def test_sweep_scheduler_sweep_id_no_job(user, monkeypatch):
    _patch_wandb_run(monkeypatch)
    sweep_config = SWEEP_CONFIG_RANDOM

    def mock_run_complete_scheduler(self, *args, **kwargs):
        self.state = SchedulerState.COMPLETED

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler.run",
        mock_run_complete_scheduler,
    )
    _entity = user
    _project = "test-project"
    api = internal.Api()
    # Entity, project, and sweep
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    # No job
    scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    scheduler.start()  # should raise no job found
    assert scheduler.state == SchedulerState.FAILED


def test_sweep_scheduler_sweep_id_with_job(user, monkeypatch):
    _patch_wandb_run(monkeypatch)
    sweep_config = SWEEP_CONFIG_RANDOM

    # make a job
    run = wandb.init()
    job_artifact = run._log_job_artifact_with_image("ljadnfakehbbr", args=[])
    job_name = job_artifact.wait().name
    sweep_config["job"] = job_name
    run.finish()

    def mock_run_complete_scheduler(self, *args, **kwargs):
        self.state = SchedulerState.COMPLETED

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler.run",
        mock_run_complete_scheduler,
    )

    _entity = user
    _project = "test-project"
    api = internal.Api()
    # Entity, project, and sweep
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    # Yes job
    scheduler = SweepScheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    scheduler.start()  # should raise no job found
    assert scheduler.state == SchedulerState.FAILED


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_scheduler_states(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    _entity = user
    _project = "test-project"
    api = internal.Api()
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

    def mock_run_complete_scheduler(self, *args, **kwargs):
        self.state = SchedulerState.COMPLETED

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._update_run_states",
        mock_run_complete_scheduler,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive is True
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive is False

    def mock_run_raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._update_run_states",
        mock_run_raise_keyboard_interrupt,
    )

    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    _scheduler.start()
    assert _scheduler.state == SchedulerState.STOPPED
    assert _scheduler.is_alive is False

    def mock_run_raise_exception(*args, **kwargs):
        raise Exception("Generic exception")

    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    _scheduler._update_run_states = mock_run_raise_exception
    with pytest.raises(Exception) as e:
        _scheduler.start()
    assert "Generic exception" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive is False

    def mock_run_exit(self, *args, **kwargs):
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._update_run_states",
        mock_run_exit,
    )

    def mock_get_run_state(*args, **kwargs):
        if args[0] == "sweep-scheduler":
            return "running"
        return "finished"

    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    _scheduler._get_run_state = mock_get_run_state
    _scheduler.start()
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive is False


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_run_states(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    _entity = user
    _project = "test-project"
    api = internal.Api()
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)

    # Mock api.get_run_state() to return crashed and running runs
    mock_run_states: dict[str, RunState] = {
        "run1": RunState.CRASHED,
        "run2": RunState.FAILED,
        "run3": RunState.KILLED,
        "run4": RunState.FINISHED,
        "run5": RunState.RUNNING,
        "run6": RunState.PENDING,
        "run7": RunState.PREEMPTED,
        "run8": RunState.PREEMPTING,
        "run9": RunState.UNKNOWN,
        "run10": "?????",
    }

    def mock_get_run_state(entity, project, run_id, *args, **kwargs):
        if run_id not in mock_run_states:  # is scheduler
            return RunState.RUNNING
        return mock_run_states[run_id]

    api.get_run_state = mock_get_run_state
    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    # Load up the runs into the Scheduler run dict
    for i, run_id in enumerate(mock_run_states.keys()):
        _scheduler._runs[run_id] = SweepRun(
            id=run_id, state=RunState.RUNNING, worker_id=i
        )
    _scheduler._update_run_states()
    for run_id, _state in mock_run_states.items():
        if _state == "?????":  # unknown state should be considered alive, but unknown
            assert _scheduler._runs[run_id].state == RunState.UNKNOWN
            continue
        if not _state.is_alive:
            # Dead runs should be removed from the run dict
            assert run_id not in _scheduler._runs
        else:
            assert _scheduler._runs[run_id].state == _state

    # ---- If get_run_state errors out, runs should have the state UNKNOWN
    def mock_get_run_state_raise_exception(*args, **kwargs):
        raise CommError("Generic Exception")

    api.get_run_state = mock_get_run_state_raise_exception
    sweep_id = wandb.sweep(sweep_config, entity=_entity, project=_project)
    _scheduler = Scheduler(
        api, sweep_id=sweep_id, entity=_entity, project=_project, num_workers=1
    )
    _scheduler._runs["foo_run_1"] = SweepRun(
        id="foo_run_1", state=RunState.RUNNING, worker_id=1
    )
    _scheduler._runs["foo_run_2"] = SweepRun(
        id="foo_run_2", state=RunState.RUNNING, worker_id=2
    )
    _scheduler._update_run_states()
    assert _scheduler._runs["foo_run_1"].state == RunState.UNKNOWN
    assert _scheduler._runs["foo_run_2"].state == RunState.UNKNOWN


@patch.multiple(Scheduler, __abstractmethods__=set())
def test_sweep_scheduler_base_add_to_launch_queue(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    api = internal.Api()

    _project = "test-project"
    _job = "test-job:latest"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    def mock_launch_add(*args, **kwargs):
        mock = Mock(spec=public.QueuedRun)
        mock.args = Mock(return_value=args)
        return mock

    monkeypatch.setattr(
        "wandb.sdk.launch._launch_add._launch_add",
        mock_launch_add,
    )

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    def mock_run_add_to_launch_queue(self, *args, **kwargs):
        self._runs["foo_run"] = SweepRun(
            id="foo_run",
            worker_id=0,
            args={"foo": {"value": 1}},
        )
        self._add_to_launch_queue(self._runs["foo_run"])
        self.state = SchedulerState.COMPLETED
        self.exit()

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._get_next_sweep_run",
        mock_run_add_to_launch_queue,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    def mock_stop_run(self, run_id):
        self._runs[run_id].state = RunState.CRASHED
        return True

    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._stop_run",
        mock_stop_run,
    )

    _scheduler = Scheduler(
        api,
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        project_queue=_project,
        polling_sleep=0,
        num_workers=1,
        job=_job,
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive is True
    assert _scheduler._project_queue == _project
    _scheduler.start()
    assert _scheduler.state == SchedulerState.COMPLETED
    assert _scheduler.is_alive is False
    assert len(_scheduler._runs) == 1
    assert isinstance(_scheduler._runs["foo_run"].queued_run, public.QueuedRun)
    _scheduler._runs["foo_run"].queued_run.state = RunState.FINISHED
    assert _scheduler._runs["foo_run"].queued_run.args()[-2] == _project

    sweep_id2 = wandb.sweep(sweep_config, entity=user, project=_project)
    _project_queue = "test-project-queue"
    _scheduler2 = Scheduler(
        api,
        sweep_id=sweep_id2,
        entity=user,
        project=_project,
        project_queue=_project_queue,
        polling_sleep=0,
        job=_job,
        num_workers=1,
    )
    _scheduler2.start()
    assert len(_scheduler2.busy_workers) == 1
    assert len(_scheduler2.available_workers) == 0
    assert _scheduler2._runs["foo_run"].queued_run.args()[-2] == _project_queue


def test_sweep_scheduler_sweeps_stop_agent_heartbeat(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    api = internal.Api()

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "stop"}]

    api.agent_heartbeat = mock_agent_heartbeat

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    _project = "test-project"
    _job = "test-job:latest"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    scheduler = SweepScheduler(
        api,
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        job=_job,
    )
    scheduler.start()
    assert scheduler.state == SchedulerState.STOPPED


def test_sweep_scheduler_sweep_deleted(user, monkeypatch):
    """Test that scheduler stops gracefully when sweep is deleted (404)."""
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    api = internal.Api()

    def mock_agent_heartbeat(*args, **kwargs):
        raise SweepNotFoundError("Sweep not found")

    api.agent_heartbeat = mock_agent_heartbeat

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    _project = "test-project"
    _job = "test-job:latest"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    scheduler = SweepScheduler(
        api,
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        job=_job,
    )
    scheduler.start()
    assert scheduler.state == SchedulerState.STOPPED


def test_sweep_scheduler_sweeps_invalid_agent_heartbeat(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

    api = internal.Api()
    _project = "test-project"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "foo"}]

    api.agent_heartbeat = mock_agent_heartbeat

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    with pytest.raises(SchedulerError) as e:
        _scheduler = SweepScheduler(
            api,
            sweep_id=sweep_id,
            entity=user,
            project=_project,
            polling_sleep=0,
            num_workers=1,
        )
        _scheduler.start()

    assert "unknown command" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive is False

    def mock_agent_heartbeat(*args, **kwargs):
        return [{"type": "run"}]  # No run_id should throw error

    api.agent_heartbeat = mock_agent_heartbeat
    api.get_run_state = mock_get_run_state

    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    with pytest.raises(SchedulerError) as e:
        _scheduler = SweepScheduler(
            api,
            sweep_id=sweep_id,
            entity=user,
            project=_project,
            polling_sleep=0,
            num_workers=1,
        )
        _scheduler.start()

    assert "No run id in agent heartbeat: {'type': 'run'}" in str(e.value)
    assert _scheduler.state == SchedulerState.FAILED
    assert _scheduler.is_alive is False


def test_sweep_scheduler_sweeps_run_and_heartbeat(user, monkeypatch):
    sweep_config = SWEEP_CONFIG_RANDOM
    _patch_wandb_run(monkeypatch)
    monkeypatch.setattr(
        "wandb.sdk.launch.sweeps.scheduler.Scheduler._try_load_executable",
        lambda _: True,
    )

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
        + [[{"type": "stop", "run_cap": 7}]]
    )

    def mock_launch_add(*args, **kwargs):
        return Mock(spec=public.QueuedRun)

    monkeypatch.setattr(
        "wandb.sdk.launch._launch_add._launch_add",
        mock_launch_add,
    )

    def mock_get_run_state(*args, **kwargs):
        if args[2] == "sweep-scheduler":
            return "running"
        return "finished"

    api.get_run_state = mock_get_run_state

    def mock_stop_run(*args, **kwargs):
        return False

    api.stop_run = mock_stop_run

    _project = "test-project"
    _job = "test-job:latest"
    sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    _scheduler = SweepScheduler(
        api,
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        job=_job,
    )
    assert _scheduler.state == SchedulerState.PENDING
    assert _scheduler.is_alive is True
    _scheduler.start()
    assert "mock-run-id-1" not in _scheduler._runs


def test_launch_sweep_scheduler_try_executable_works(user, test_settings, monkeypatch):
    _patch_wandb_run(monkeypatch)
    _project = "test-project"
    settings = test_settings({"project": _project})
    run = wandb.init(settings=settings)
    job_artifact = run._log_job_artifact_with_image("lala-docker-123", args=[])
    job_name = f"{user}/{_project}/{job_artifact.wait().name}"

    run.finish()
    sweep_id = wandb.sweep(SWEEP_CONFIG_RANDOM, entity=user, project=_project)

    _scheduler = SweepScheduler(
        internal.Api(),
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        job=job_name,
    )

    assert _scheduler._try_load_executable()


def test_launch_sweep_scheduler_try_executable_fails(user, monkeypatch):
    _patch_wandb_run(monkeypatch)
    _project = "test-project"
    job_name = "nonexistent"
    sweep_id = wandb.sweep(SWEEP_CONFIG_RANDOM, entity=user, project=_project)

    _scheduler = SweepScheduler(
        internal.Api(),
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        job=job_name,
    )

    _scheduler.start()

    assert _scheduler.state == SchedulerState.FAILED


def test_launch_sweep_scheduler_try_executable_image(user, monkeypatch):
    _patch_wandb_run(monkeypatch)
    _project = "test-project"
    _image_uri = "some-image-wow"
    sweep_id = wandb.sweep(SWEEP_CONFIG_RANDOM, entity=user, project=_project)

    _scheduler = SweepScheduler(
        internal.Api(),
        sweep_id=sweep_id,
        entity=user,
        project=_project,
        num_workers=1,
        polling_sleep=0,
        image_uri=_image_uri,
    )

    assert _scheduler._try_load_executable()


@pytest.mark.parametrize(
    "sweep_config",
    [{"job": "job:v9"}, {"image_uri": "image:latest"}],
)
def test_launch_sweep_scheduler_construct_entrypoint(sweep_config):
    queue = "queue"
    project = "test"

    args = construct_scheduler_args(
        return_job=False,
        sweep_config=sweep_config,
        queue=queue,
        project=project,
        author="author",
    )

    gold_args = [
        "--queue",
        f"{queue!r}",
        "--project",
        f"{project!r}",
        "--author",
        "'author'",
    ]
    if sweep_config.get("job"):
        gold_args += ["--job", "'job:v9'"]
    else:
        gold_args += ["--image_uri", "image:latest"]

    assert args == gold_args


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["python", "train.py", "${args_no_hyphens}"],
        ["python", "train.py", "${args_append_hydra}"],
        ["python", "train.py", "${args_override_hydra}"],
        ["python", "train.py", "${args_no_equals}"],
        ["${env}", "python", "train.py", "${args}", "--another", "param"],
        ["python", "train.py", "--float", 1.99999, "${args_json}"],
    ],
)
def test_launch_sweep_scheduler_macro_args(user, monkeypatch, command):
    _patch_wandb_run(monkeypatch)

    def mock_launch_add(*args, **kwargs):
        mock = Mock(spec=public.QueuedRun)
        mock.args = Mock(return_value=args)
        return mock

    monkeypatch.setattr(
        "wandb.sdk.launch._launch_add._launch_add",
        mock_launch_add,
    )

    sweep_config = {
        "job": "job:latest",
        "program": "program-override.py",
        "method": "grid",
        "parameters": {
            "foo-1": {"values": [1, 2]},
            "bool_2": {"values": [True, False]},
        },
        "command": command,
    }
    # Entity, project, and sweep should be everything you need to create a scheduler
    api = internal.Api()
    s = wandb.sweep(sweep_config, entity=user, project="t")
    scheduler = SweepScheduler(
        api, sweep_id=s, entity=user, project="t", queue="q", num_workers=1
    )
    asyncio.run(scheduler._register_agents())
    srun2 = scheduler._get_next_sweep_run(0)
    scheduler._add_to_launch_queue(srun2)
