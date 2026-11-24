"""Agent tests."""

import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import wandb
import wandb.agents.pyagent as pyagent
from wandb.apis.public import Api

from .test_wandb_sweep import SWEEP_CONFIG_GRID


def test_public_api_sweep_agent_retrieves_running_agent(user):
    """While a sweep agent is blocked in user code, Api().sweep().agent() returns it."""
    project = "test-public-api-sweep-agent-retrieves-running-agent"
    sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user, project=project)

    agent_id_queue = queue.Queue()
    exit_lock = threading.Event()

    def train():
        with wandb.init():
            agent_id_queue.put(agent._agent_id)
            exit_lock.wait()

    agent = pyagent.Agent(
        sweep_id,
        function=train,
        entity=user,
        project=project,
        count=1,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(agent.run)
        try:
            agent_id = agent_id_queue.get()
            api = Api()
            sweep = api.sweep(f"{user}/{project}/sweeps/{sweep_id}")
            agents = sweep.agents()
            assert len(agents) > 0
            first = agents[0]
            assert first.id == agent_id and first.state
            by_name = sweep.agent(first.name)
            assert by_name.id == agent_id and by_name.state
        finally:
            exit_lock.set()


def test_public_api_sweep_agent_runs_lists_finished_run(user):
    """After three sweep runs finish, Agent.runs(per_page=2) returns all three (paginated)."""
    project = "test-public-api-sweep-agent-runs-lists-finished-run"
    sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user, project=project)

    def train():
        run = wandb.init()
        run.log({"loss": 0.25})
        run.finish()

    wandb.agent(
        sweep_id,
        function=train,
        count=3,
        project=project,
        entity=user,
    )

    api = Api()
    sweep = api.sweep(f"{user}/{project}/sweeps/{sweep_id}")
    agents = sweep.agents()
    assert len(agents) >= 1
    public_agent = agents[0]
    runs_list = list(public_agent.runs(per_page=2))
    assert len(runs_list) == 3
    assert {r.state for r in runs_list} == {"finished"}


def test_normal_run_after_agent_does_not_overwrite_sweep_run(user, runner, monkeypatch):
    """After running a sweep agent, a normal wandb.init() creates a separate run.

    Matches WB-8766 and WB-38827: create sweep, run agent (1 run), then create
    a normal run without an explicit id. The normal run must be separate and
    must not overwrite the sweep run.
    """

    with runner.isolated_filesystem():
        project_name = "test-normal-run-after-agent"
        Api().create_project(project_name, user)

        sweep_run_ids = []

        def sweep_train():
            run = wandb.init()
            sweep_run_ids.append(run.id)
            run.log({"a": run.config["a"], "accuracy": run.config["a"] * 4})
            run.finish()

        sweep_config = {
            "name": "sweep-normal-run-sep",
            "method": "random",
            "metric": {"name": "accuracy", "goal": "maximize"},
            "parameters": {"a": {"values": [1, 2, 3, 4]}},
        }
        monkeypatch.setenv("WANDB_CONSOLE", "off")
        sweep_id = wandb.sweep(sweep_config, project=project_name, entity=user)
        wandb.agent(sweep_id, function=sweep_train, count=1, project=project_name)

        assert len(sweep_run_ids) == 1, "Agent should have run 1 sweep run"
        sweep_run_id = sweep_run_ids[0]

        run = wandb.init(project=project_name, entity=user)
        try:
            run.log({"accuracy": 4})
            normal_run_id = run.id
            assert normal_run_id != sweep_run_id
            assert run.sweep_id is None, "Normal run must not be part of the sweep"
            assert "a" not in run.config, "Normal run must not get the sweep config"
            # Sweep run must still exist and be unchanged (not overwritten).
            # The agent's internal wandb.teardown() between jobs invalidates
            # any wandb.Api() held from before, so create a fresh one here.
            public_api = Api()
            sweep_runs = list(
                public_api.runs(f"{user}/{project_name}", {"sweep": sweep_id})
            )
            assert len(sweep_runs) == 1, "There must still be exactly 1 sweep run"
            assert sweep_run_id in {r.id for r in sweep_runs}
        finally:
            run.finish()

        # Normal run should appear as its own run, not under the sweep.
        all_runs = list(public_api.runs(f"{user}/{project_name}"))
        run_ids = {r.id for r in all_runs}
        assert normal_run_id in run_ids
        assert sweep_run_id in run_ids


_OVERLAPPING_TRAIN_SCRIPT = """
import os
import pathlib
import time

import wandb

started = pathlib.Path(os.environ["SWEEP_TEST_STARTED_DIR"])
overlapped = pathlib.Path(os.environ["SWEEP_TEST_OVERLAPPED_DIR"])

with wandb.init() as run:
    (started / run.id).touch()
    # Hold the run open until another agent has started one too, so the two
    # agents are heartbeating against the sweep at the same time.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if len(list(started.iterdir())) >= 2:
            (overlapped / run.id).touch()
            break
        time.sleep(0.2)
    run.log({"loss": run.config["param1"]})
"""


def test_two_agents_split_one_grid_sweep(user, tmp_path):
    """Two `wandb agent` processes on one grid sweep run at the same time,
    each registers as its own agent, and together they run every grid point
    exactly once."""
    project = "test-two-agents-one-sweep"
    (tmp_path / "train.py").write_text(_OVERLAPPING_TRAIN_SCRIPT)
    started_dir = tmp_path / "started"
    overlapped_dir = tmp_path / "overlapped"
    started_dir.mkdir()
    overlapped_dir.mkdir()

    sweep_config = {
        "name": "two-agents-grid",
        "method": "grid",
        "program": "train.py",
        "command": ["${env}", sys.executable, "${program}", "${args}"],
        "parameters": {"param1": {"values": [1, 2, 3, 4]}},
    }
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    env = {
        **os.environ,
        "WANDB_CONSOLE": "off",
        "SWEEP_TEST_STARTED_DIR": str(started_dir),
        "SWEEP_TEST_OVERLAPPED_DIR": str(overlapped_dir),
    }
    agent_cmd = [
        sys.executable,
        "-m",
        "wandb",
        "agent",
        "--count",
        "2",
        "--entity",
        user,
        "--project",
        project,
        sweep_id,
    ]
    agents = [
        subprocess.Popen(
            agent_cmd,
            cwd=tmp_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(2)
    ]
    outputs = [proc.communicate(timeout=600)[0] for proc in agents]
    for proc, output in zip(agents, outputs, strict=True):
        assert proc.returncode == 0, output

    assert len(list(overlapped_dir.iterdir())) >= 2, "the agents never overlapped"

    sweep = Api().sweep(f"{user}/{project}/sweeps/{sweep_id}")
    public_agents = sweep.agents()
    assert len(public_agents) == 2
    assert all(len(list(a.runs())) == 2 for a in public_agents)

    runs = list(sweep.runs)
    assert sorted(r.config["param1"] for r in runs) == [1, 2, 3, 4]
    assert {r.state for r in runs} == {"finished"}
