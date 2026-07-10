"""Agent tests."""

import contextlib
import io
import pathlib
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import wandb
import wandb.agents.pyagent as pyagent
from wandb.apis.public import Api
from wandb.cli import cli
from wandb.sdk.launch.sweeps import SweepNotFoundError

from .test_wandb_sweep import SWEEP_CONFIG_GRID


def test_agent_basic(user):
    sweep_ids = []
    sweep_configs = []
    sweep_resumed = []
    project = "test-agent-basic"

    sweep_config = {
        "name": "test-agent-basic",
        "method": "grid",
        "parameters": {"a": {"values": [1]}},
    }

    def train():
        run = wandb.init()
        sweep_ids.append(run.sweep_id)
        sweep_configs.append(dict(run.config))
        sweep_resumed.append(run.resumed)
        run.finish()

    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)

    assert len(sweep_ids) == len(sweep_configs) == 1
    assert sweep_ids[0] == sweep_id
    assert sweep_configs[0] == {"a": 1}
    assert sweep_resumed[0] is False


def test_agent_config_merge(user, monkeypatch):
    sweep_configs = []
    project = "test-agent-config-merge"

    def train():
        run = wandb.init(config={"extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    sweep_config = {
        "name": "test-agent-config-merge",
        "method": "grid",
        "parameters": {"a": {"values": [1]}},
    }

    monkeypatch.setenv("WANDB_CONSOLE", "off")
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)
    wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_config_whitespace_py_agent(user, monkeypatch):
    ran = False
    project = "test-agent-config-whitespace-py-agent"

    def train():
        nonlocal ran
        run = wandb.init()
        assert run.config["a"] == "one two"
        assert run.config["b"] == "three four"
        assert run.config["c"] == '"five six"'
        run.finish()
        ran = True

    sweep_config = {
        "name": "test-agent-config-whitespace-py-agent",
        "method": "grid",
        "parameters": {
            "a": {"values": ["one two"]},
            "b": {"value": "three four"},
            "c": {"value": '"five six"'},
        },
    }

    monkeypatch.setenv("WANDB_CONSOLE", "off")
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)
    wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)
    assert ran


def test_agent_config_whitespace_cli_agent(runner, user):
    project = "test-whitespace-cli-agent"
    with runner.isolated_filesystem():
        pathlib.Path("test.py").write_text(
            "import wandb\n"
            "\n"
            "run = wandb.init()\n"
            "assert run.config['a'] == 'one two'\n"
            "assert run.config['b'] == 'three four'\n"
            "run.finish()\n"
        )

        sweep_config = {
            "name": "My Sweep",
            "program": "test.py",
            "method": "grid",
            "parameters": {"a": {"values": ["one two"]}, "b": {"value": "three four"}},
        }

        sweep_id = wandb.sweep(sweep_config, project=project)
        runner.invoke(cli.agent, [sweep_id])

    runs = Api().runs(project, {"sweep": sweep_id})
    assert len(runs) == 1
    assert runs[0].state == "finished"


def test_agent_config_ignore(user):
    sweep_configs = []
    project = "test-agent-config-ignore"

    def train():
        run = wandb.init(config={"a": "ignored", "extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    sweep_config = {
        "name": "test-agent-config-ignore",
        "method": "grid",
        "parameters": {"a": {"values": [1]}},
    }

    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)
    wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_ignore_project_entity_run_id(user):
    sweep_entities = []
    sweep_projects = []
    sweep_run_ids = []

    project_name = "test-agent-ignore-project-entity-run-id"
    public_api = Api()
    public_api.create_project(project_name, user)

    def train():
        run = wandb.init(entity="ign", project="ignored", id="also_ignored")
        sweep_projects.append(run.project)
        sweep_entities.append(run.entity)
        sweep_run_ids.append(run.id)
        run.finish()

    sweep_config = {
        "name": "test-agent-ignore-project-entity-run-id",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project_name)
    wandb.agent(sweep_id, function=train, count=1, entity=user, project=project_name)

    assert len(sweep_projects) == len(sweep_entities) == 1
    assert sweep_projects[0] == project_name
    assert sweep_entities[0] == user
    assert sweep_run_ids[0] != "also_ignored"


def test_agent_exception(user):
    project = "test-agent-exception"
    sweep_config = {
        "name": "test-agent-exception",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    def train():
        wandb.init()
        raise Exception("Unexpected error")

    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)

    stderr_lines = captured_stderr.getvalue().splitlines()

    # Traceback with exception should appear before we finish the run.
    patterns = ["Traceback", "Exception: Unexpected error", "wandb: Find logs at:"]
    current_pattern = 0

    for line in stderr_lines:
        if line.startswith(patterns[current_pattern]):
            current_pattern += 1
            if current_pattern == len(patterns):
                break

    # Verify all patterns were found in order
    assert current_pattern == len(patterns), (
        f"Not found in stderr: '{patterns[current_pattern]}'"
    )


def test_agent_subprocess_with_import_readline(user, monkeypatch):
    """Test that wandb.agent works safely when subprocess imports readline."""
    script_path = pathlib.Path(__file__).parent / "train_with_import_readline.py"

    project = "train-with-import-readline"
    sweep_config = {
        "name": "Train with import readline",
        "method": "grid",
        "parameters": {"test_param": {"values": [1]}},
        "command": ["python", str(script_path)],
    }
    sweep_id = wandb.sweep(sweep_config, project=project)

    monkeypatch.setenv("WANDB_AGENT_MAX_INITIAL_FAILURES", "1")
    wandb.agent(sweep_id, count=1)
    # We'll just rely on the default pytest 60s timeout if it deadlocks.

    runs = Api().runs(project, {"sweep": sweep_id})
    assert len(runs) == 1
    history = runs[0].history(pandas=False)
    assert history[0]["got_eof"]
    assert history[0]["test_param"] == 1


def test_agent_sweep_deleted(user):
    """Test that agent exits gracefully when sweep is deleted (404)."""
    project = "test-agent-sweep-deleted"
    sweep_config = {
        "name": "test-agent-sweep-deleted",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        with mock.patch(
            "wandb.sdk.internal.internal_api.Api.agent_heartbeat",
            side_effect=SweepNotFoundError("Sweep not found"),
        ):
            wandb.agent(
                sweep_id, function=lambda: None, count=1, entity=user, project=project
            )

    stderr_output = captured_stderr.getvalue()
    assert "Sweep was deleted or agent was not found" in stderr_output


def test_agent_sweep_deleted_waits_for_in_flight_run(user, monkeypatch):
    """A 404 on heartbeat must not stop the agent while a trial thread is still running.

    The trial deliberately stays in user code until the agent has handled the 404
    and logged the "in-process run will be allowed to finish" message. That message
    is emitted (from the heartbeat thread) only after the agent confirms a trial
    thread is still alive, so the trial is provably in flight across the 404 check.

    The trial does not call ``wandb.init()``: the agent's 404 handling only checks
    whether the trial thread is alive (``_has_running_thread``), so a real run is
    unnecessary, and creating one is racy under the agent's concurrent teardown and
    heartbeat (it intermittently failed with "user is not logged in" on CI).
    Coordination uses a ``wandb.termerror`` spy rather than capturing stderr.
    """
    project = "test-agent-sweep-deleted-waits-for-in-flight-run"
    sweep_config = {
        "name": "test-agent-sweep-deleted-waits-for-in-flight-run",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }
    sweep_id = wandb.sweep(sweep_config, entity=user, project=project)

    wait_msg = "in-process run will be allowed to finish"

    first_heartbeat_done = threading.Event()
    trial_in_user_code = threading.Event()
    waited_for_in_flight_run = threading.Event()
    termerrors: list[str] = []

    # Use a short (non-zero) heartbeat interval: fast enough to keep the test
    # snappy, but without a hot spin that hammers the shared API lock.
    monkeypatch.setattr(pyagent.Agent, "HEARTBEAT_SLEEP_SECONDS", 0.05)

    real_termerror = wandb.termerror

    def termerror_spy(message, *args, **kwargs):
        termerrors.append(message)
        if wait_msg in message:
            waited_for_in_flight_run.set()
        return real_termerror(message, *args, **kwargs)

    monkeypatch.setattr(wandb, "termerror", termerror_spy)

    def train():
        # Announce that the trial is in user code, then stay here until the
        # agent has logged that it is waiting for the in-flight run. The agent
        # only logs that after confirming this thread is still alive, so the
        # trial stays provably in flight across the 404 check.
        trial_in_user_code.set()
        assert waited_for_in_flight_run.wait(timeout=30), (
            "agent did not log the in-flight wait message before timeout"
        )

    def agent_heartbeat_mock(agent_id, metrics, run_states):
        if not first_heartbeat_done.is_set():
            first_heartbeat_done.set()
            return [
                {
                    "type": "run",
                    "run_id": "sweep-deleted-wait-run",
                    "args": {"a": {"value": 1}},
                    "program": "train.py",
                }
            ]
        # Only raise the 404 once the trial is actually executing user code.
        # Return an empty command list (rather than blocking) until then: the
        # agent calls this under `Agent._api_lock`, and the run thread needs that
        # same lock to start the trial, so blocking here would deadlock.
        if not trial_in_user_code.is_set():
            return []
        raise SweepNotFoundError("Sweep not found")

    with mock.patch(
        "wandb.sdk.internal.internal_api.Api.agent_heartbeat",
        side_effect=agent_heartbeat_mock,
    ):
        wandb.agent(sweep_id, function=train, count=1, entity=user, project=project)

    assert any(wait_msg in message for message in termerrors)


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
