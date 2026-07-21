"""Agent tests."""

import os
import platform
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest
from wandb.apis.public.sweeps import Agent as PublicAgent
from wandb.sdk.launch.sweeps.utils import (
    create_sweep_command,
    create_sweep_command_args,
)
from wandb.wandb_agent import Agent


def test_public_agent_repr():
    """Public API Agent.__repr__ uses id and state from attrs."""
    agent = PublicAgent(
        mock.Mock(),
        attrs={"id": "test-agent-id", "state": "RUNNING"},
        entity="test-entity",
        project="test-project",
        sweep_id="test-sweep",
    )
    assert repr(agent) == "<Agent test-agent-id (RUNNING)>"


def test_agent_create_command_args():
    mock_command = {
        "args": {
            "a": {"value": True},
            "b": {"value": False},
            "c": {"value": 1},
            "d": {"value": None},
        }
    }

    _return = create_sweep_command_args(mock_command)
    # test has all the required fields
    assert "args" in _return
    assert "args_no_hyphens" in _return
    assert "args_append_hydra" in _return
    assert "args_override_hydra" in _return
    assert "args_no_boolean_flags" in _return
    assert "args_json" in _return
    # test fields are correct
    assert _return["args"] == ["--a=True", "--b=False", "--c=1", "--d=None"]
    assert _return["args_no_hyphens"] == ["a=True", "b=False", "c=1", "d=None"]
    assert _return["args_no_boolean_flags"] == ["--a", "--c=1", "--d=None"]
    assert _return["args_json"] == ['{"a": true, "b": false, "c": 1, "d": null}']
    assert _return["args_append_hydra"] == ["+a=True", "+b=False", "+c=1", "+d=None"]
    assert _return["args_override_hydra"] == [
        "++a=True",
        "++b=False",
        "++c=1",
        "++d=None",
    ]


def test_agent_create_command_args_bad_command():
    mock_command_no_args = {"foo": None}
    with pytest.raises(ValueError):
        _ = create_sweep_command_args(mock_command_no_args)
    mock_command_missing_value = {"args": {"a": {"foo": True}}}
    with pytest.raises(ValueError):
        _ = create_sweep_command_args(mock_command_missing_value)


@mock.patch.dict(
    os.environ,
    {
        "FOO_DIR": "foo_dir",
        "FOO_DIR_TWO": "foo_dir_two",
        "FOO_VAR": "foo_var",
    },
)
def test_agent_create_sweep_command():
    # Given no command, function should return default
    _command = create_sweep_command()
    assert _command == Agent.DEFAULT_SWEEP_COMMAND

    # Environment variable macros should be replaced in mock command
    _command = create_sweep_command(
        [
            "${env}",
            "${interpreter}",
            "--output_dir",
            "fake/path/${envvar:FOO_DIR}/${envvar:FOO_DIR}/${envvar:FOO_DIR_TWO}",
            "--foovar",
            "${envvar:FOO_VAR}",
        ]
    )
    assert _command == [
        "${env}",
        "${interpreter}",
        "--output_dir",
        "fake/path/foo_dir/foo_dir/foo_dir_two",
        "--foovar",
        "foo_var",
    ]


def _write_signal_child_script(path: Path) -> Path:
    script = path / "child_signal.py"
    script.write_text(
        textwrap.dedent(
            """
            import pathlib
            import signal
            import sys
            import time

            marker = pathlib.Path(sys.argv[1])

            def _handle(signum, frame):
                marker.write_text(str(signum))
                sys.exit(0)

            signal.signal(signal.SIGTERM, _handle)
            signal.signal(signal.SIGINT, _handle)

            while True:
                time.sleep(0.1)
            """
        ).strip()
    )
    return script


def _write_signal_parent_script(path: Path) -> Path:
    script = path / "parent_signal.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            import signal
            import sys
            import time
            from pathlib import Path

            from wandb.wandb_agent import AgentProcess

            marker = Path(sys.argv[1])
            child_script = Path(sys.argv[2])

            signal.signal(signal.SIGTERM, lambda s, f: None)

            proc = AgentProcess(
                env=dict(os.environ),
                command=[sys.executable, str(child_script), str(marker)],
                forward_signals=True,
            )

            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)

            deadline = time.time() + 10
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.1)

            if proc.poll() is None:
                proc.terminate()
                sys.exit(2)

            if not marker.exists():
                sys.exit(3)
            """
        ).strip()
    )
    return script


def _write_ignore_signals_child_script(path: Path) -> Path:
    script = path / "child_ignore_signals.py"
    script.write_text(
        textwrap.dedent(
            """
            import signal
            import time

            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)

            while True:
                time.sleep(0.1)
            """
        ).strip()
    )
    return script


def _write_term_timeout_parent_script(path: Path) -> Path:
    """Similar to _write_signal_parent_script, but uses an Agent to manage the
    AgentProcess lifecycle, isntead of using AgentProcess directly, which allows us to
    pass in a term_timeout parameter."""

    script = path / "parent_term_timeout.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            import queue
            import signal
            import sys
            import threading
            import time

            from wandb.wandb_agent import Agent

            child_script = sys.argv[1]
            term_timeout = int(sys.argv[2])

            class _StubApi:
                def sweep(self, sweep_id, spec):
                    return None

                def register_agent(self, host, sweep_id=None):
                    return {"id": "agent-1"}

                def agent_heartbeat(self, agent_id, spec, run_status):
                    return []

            # Seed agent command queue to run the child script
            command_queue = queue.Queue()
            command_queue.put(
                {
                    "type": "run",
                    "run_id": "run-1",
                    "program": child_script,
                    "args": {},
                    "resp_queue": queue.Queue(),
                }
            )

            agent = Agent(
                _StubApi(),
                command_queue,
                sweep_id="sweep-1",
                term_timeout=term_timeout,
                forward_signals=True,
            )

            # Send a SIGINT after 1 second. This is eaten by then child process but
            # puts the Agent into the tier 1 waiting state.
            threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGINT)).start()

            start = time.monotonic()
            agent.run()
            elapsed = time.monotonic() - start

            procs = list(agent._run_processes.values())
            child = procs[0]

            returncode = child.wait(timeout=5)
            if returncode != -signal.SIGKILL:
                sys.exit(2)

            # We expect that the child terminated roughly around the term_timeout time
            if elapsed > term_timeout * 2:
                sys.exit(3)
            if elapsed < term_timeout * 0.5:
                sys.exit(4)
            """
        ).strip()
    )
    return script


@pytest.mark.skipif(
    platform.system() == "Windows", reason="POSIX signals required for this test"
)
def test_agent_process_forwards_signals_end_to_end(tmp_path):
    marker = tmp_path / "signal.txt"
    child_script = _write_signal_child_script(tmp_path)
    parent_script = _write_signal_parent_script(tmp_path)

    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{env['PYTHONPATH']}"
        if "PYTHONPATH" in env and env["PYTHONPATH"]
        else str(repo_root)
    )

    result = subprocess.run(
        [sys.executable, str(parent_script), str(marker), str(child_script)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert marker.exists()
    assert marker.read_text().strip() == str(int(signal.SIGTERM))


@pytest.mark.skipif(
    platform.system() == "Windows", reason="POSIX signals required for this test"
)
def test_agent_term_timeout_escalates_to_sigkill(tmp_path):
    """Checks that a child that ignores signals past `term_timeout` is
    escalated straight to SIGKILL rather than re-sent a polite SIGTERM."""

    child_script = _write_ignore_signals_child_script(tmp_path)
    parent_script = _write_term_timeout_parent_script(tmp_path)
    term_timeout = 3

    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{env['PYTHONPATH']}"
        if "PYTHONPATH" in env and env["PYTHONPATH"]
        else str(repo_root)
    )

    result = subprocess.run(
        [
            sys.executable,
            str(parent_script),
            str(child_script),
            str(term_timeout),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=60,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_agent_cli_exit_code_on_sweep_not_found(runner, user):
    """CLI agent returns exit code 1 when sweep doesn't exist."""
    from wandb.cli import cli

    # Use a non-existent sweep ID - the API will return 404
    fake_sweep_id = "nonexistent12"

    result = runner.invoke(cli.agent, [fake_sweep_id])

    assert result.exit_code == 1, (
        f"Expected exit code 1 for non-existent sweep, got {result.exit_code}. "
        f"output:\n{result.output}"
    )
