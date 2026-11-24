"""Sweep lifecycle tests: the states a sweep moves through, read back from the server."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import wandb
import wandb.agents.pyagent as pyagent
from wandb.apis.public import Api
from wandb.cli import cli

SWEEP_CONFIG_GRID = {
    "name": "lifecycle-grid",
    "method": "grid",
    "parameters": {"param1": {"values": [1, 2, 3]}},
}


def _sweep_state(user: str, project: str, sweep_id: str) -> str:
    # Api caches sweeps per instance, so use a new one for each read.
    return Api().sweep(f"{user}/{project}/sweeps/{sweep_id}").state


def _sweep_runs(user: str, project: str, sweep_id: str) -> list:
    return list(Api().sweep(f"{user}/{project}/sweeps/{sweep_id}").runs)


@pytest.fixture
def fast_heartbeat(monkeypatch):
    monkeypatch.setattr(pyagent.Agent, "HEARTBEAT_SLEEP_SECONDS", 0.5)
    monkeypatch.setenv("WANDB_CONSOLE", "off")


class _BlockingTrain:
    """A sweep function that holds each run open until `release` is set."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.configs: list[dict] = []

    def __call__(self) -> None:
        with wandb.init() as run:
            self.configs.append(dict(run.config))
            self.started.set()
            assert self.release.wait(timeout=120), "test never released the run"
            run.log({"loss": 0.1})


def test_sweep_moves_pending_running_finished(user, fast_heartbeat):
    """A grid sweep starts PENDING, is RUNNING once an agent attaches, and is
    FINISHED after the agent exhausts the grid."""
    project = "test-sweep-lifecycle"
    sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user, project=project)
    assert _sweep_state(user, project, sweep_id) == "PENDING"

    train = _BlockingTrain()
    agent = pyagent.Agent(sweep_id, function=train, entity=user, project=project)

    with ThreadPoolExecutor(max_workers=1) as executor:
        done = executor.submit(agent.run)
        try:
            assert train.started.wait(timeout=120), "agent never started a run"
            assert _sweep_state(user, project, sweep_id) == "RUNNING"
        finally:
            train.release.set()
        # The agent exits when the server reports the grid is exhausted.
        done.result(timeout=300)

    assert _sweep_state(user, project, sweep_id) == "FINISHED"
    runs = _sweep_runs(user, project, sweep_id)
    assert sorted(r.config["param1"] for r in runs) == [1, 2, 3]
    assert {r.state for r in runs} == {"finished"}


def test_stop_lets_the_current_run_finish_and_starts_no_more(
    user, runner, fast_heartbeat
):
    """`wandb sweep --stop` stores FINISHED at once (there is no STOPPING
    state). The agent's in-flight run completes, no further run starts, and
    the agent exits."""
    project = "test-sweep-lifecycle-stop"
    sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user, project=project)

    train = _BlockingTrain()
    agent = pyagent.Agent(sweep_id, function=train, entity=user, project=project)

    with ThreadPoolExecutor(max_workers=1) as executor:
        done = executor.submit(agent.run)
        try:
            assert train.started.wait(timeout=120), "agent never started a run"
            result = runner.invoke(
                cli.sweep, ["--stop", sweep_id, "--project", project]
            )
            assert result.exit_code == 0, result.output
            assert _sweep_state(user, project, sweep_id) == "FINISHED"
        finally:
            train.release.set()
        done.result(timeout=300)

    assert len(train.configs) == 1
    runs = _sweep_runs(user, project, sweep_id)
    assert len(runs) == 1
    assert runs[0].state == "finished"
