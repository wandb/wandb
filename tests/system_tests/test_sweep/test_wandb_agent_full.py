"""Agent tests."""

import contextlib
import inspect
import io
import pathlib
import queue
import threading
from unittest import mock

import wandb
import wandb.agents.pyagent as pyagent_mod
from wandb.apis.public import Api
from wandb.cli import cli
from wandb.sdk.launch.sweeps import SweepNotFoundError

from .test_wandb_sweep import SWEEP_CONFIG_GRID


def _pyagent_agent_id_from_call_stack() -> str:
    """Resolve the active sweep `wandb.agents.pyagent.Agent` id from the call stack.

    `train()` runs inside `Agent._run_job`, so the stack contains that agent instance.
    """
    for frame_info in inspect.stack():
        self_obj = frame_info.frame.f_locals.get("self")
        if isinstance(self_obj, pyagent_mod.Agent) and self_obj._agent_id:
            return self_obj._agent_id
    msg = "could not find wandb.agents.pyagent.Agent with _agent_id on the call stack"
    raise RuntimeError(msg)


def test_agent_basic(user):
    sweep_ids = []
    sweep_configs = []
    sweep_resumed = []

    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    def train():
        run = wandb.init()
        sweep_ids.append(run.sweep_id)
        sweep_configs.append(dict(run.config))
        sweep_resumed.append(run.resumed)
        run.finish()

    sweep_id = wandb.sweep(sweep_config)

    wandb.agent(sweep_id, function=train, count=1)

    assert len(sweep_ids) == len(sweep_configs) == 1
    assert sweep_ids[0] == sweep_id
    assert sweep_configs[0] == {"a": 1}
    assert sweep_resumed[0] is False


def test_agent_config_merge(user, monkeypatch):
    sweep_configs = []

    def train():
        run = wandb.init(config={"extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    monkeypatch.setenv("WANDB_CONSOLE", "off")
    sweep_id = wandb.sweep(sweep_config)
    wandb.agent(sweep_id, function=train, count=1)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_config_whitespace_py_agent(user, monkeypatch):
    ran = False

    def train():
        nonlocal ran
        run = wandb.init()
        assert run.config["a"] == "one two"
        assert run.config["b"] == "three four"
        assert run.config["c"] == '"five six"'
        run.finish()
        ran = True

    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {
            "a": {"values": ["one two"]},
            "b": {"value": "three four"},
            "c": {"value": '"five six"'},
        },
    }

    monkeypatch.setenv("WANDB_CONSOLE", "off")
    sweep_id = wandb.sweep(sweep_config)
    wandb.agent(sweep_id, function=train, count=1)
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

    def train():
        run = wandb.init(config={"a": "ignored", "extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    sweep_id = wandb.sweep(sweep_config)
    wandb.agent(sweep_id, function=train, count=1)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_ignore_project_entity_run_id(user):
    sweep_entities = []
    sweep_projects = []
    sweep_run_ids = []

    project_name = "actual"
    public_api = Api()
    public_api.create_project(project_name, user)

    def train():
        run = wandb.init(entity="ign", project="ignored", id="also_ignored")
        sweep_projects.append(run.project)
        sweep_entities.append(run.entity)
        sweep_run_ids.append(run.id)
        run.finish()

    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }
    sweep_id = wandb.sweep(sweep_config, project=project_name)
    wandb.agent(sweep_id, function=train, count=1, project=project_name)

    assert len(sweep_projects) == len(sweep_entities) == 1
    assert sweep_projects[0] == "actual"
    assert sweep_entities[0] == user
    assert sweep_run_ids[0] != "also_ignored"


def test_agent_exception(user):
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    def train():
        wandb.init()
        raise Exception("Unexpected error")

    sweep_id = wandb.sweep(sweep_config)

    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        wandb.agent(sweep_id, function=train, count=1)

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
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"a": {"values": [1, 2, 3]}},
    }

    sweep_id = wandb.sweep(sweep_config)

    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        with mock.patch(
            "wandb.sdk.internal.internal_api.Api.agent_heartbeat",
            side_effect=SweepNotFoundError("Sweep not found"),
        ):
            wandb.agent(sweep_id, function=lambda: None, count=1)

    stderr_output = captured_stderr.getvalue()
    assert "Sweep was deleted or agent was not found" in stderr_output


def test_public_api_sweep_agent_retrieves_running_agent(user):
    """While a sweep agent is blocked in user code, Api().sweep().agent() returns it."""
    project = "test"
    sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user, project=project)

    stop = threading.Event()
    agent_id_queue: queue.Queue[str] = queue.Queue(maxsize=1)
    agent_errors: list[Exception] = []

    def train():
        wandb.init()
        agent_id_queue.put(_pyagent_agent_id_from_call_stack())
        stop.wait()
        wandb.finish()

    def run_agent():
        try:
            wandb.agent(
                sweep_id,
                function=train,
                count=1,
                project=project,
                entity=user,
            )
        except Exception as e:
            agent_errors.append(e)

    agent_thread = threading.Thread(
        target=run_agent, name="wandb-agent-test", daemon=True
    )
    agent_thread.start()

    try:
        api = Api()
        agent_id = agent_id_queue.get(timeout=90)
        sweep = api.sweep(f"{user}/{project}/sweeps/{sweep_id}")
        assert len(sweep.agents()) > 0
        retrieved = sweep.agents()[0]
        assert retrieved.id == agent_id
        assert retrieved.state

        retrieved = sweep.agent(retrieved.name)
        assert retrieved.id == agent_id
        assert retrieved.state
    finally:
        stop.set()
        agent_thread.join(timeout=120)

    assert not agent_thread.is_alive(), "agent thread did not finish after stop"
    assert not agent_errors, f"agent thread raised: {agent_errors!r}"
