"""Agent tests."""

import queue
import threading
import time
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

    Matches WB-8766: create sweep, run agent (1 run), then create a normal run
    with an explicit id. The normal run must be separate and must not overwrite
    the sweep run.
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

        # Create a normal run (not part of the sweep) with an explicit id.
        normal_run_id = f"normal-run-{hash(time.time())}"
        run = wandb.init(
            project=project_name,
            entity=user,
            config={"a": 1},
            id=normal_run_id,
        )
        try:
            run.log({"accuracy": 4})
            assert run.id == normal_run_id, "Normal run should keep the explicit id"
            assert run.sweep_id is None, "Normal run must not be part of the sweep"
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
