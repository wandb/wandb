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
from wandb.sdk.launch.sweeps.utils import (
    create_sweep_command,
    create_sweep_command_args,
)
from wandb.wandb_agent import Agent


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
