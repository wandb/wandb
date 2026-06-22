"""System tests for wandb-core Unix socket temp directory cleanup."""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from tests.unix_socket_cleanup_helpers import (
    assert_no_new_wandb_entries,
    isolated_temp_env,
    list_wandb_temp_entries,
    process_is_running,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix socket temp-dir cleanup is not supported on Windows",
)

CHILD_SCRIPT = (
    pathlib.Path(__file__).parent / "scripts" / "unix_socket_cleanup_child.py"
)
POLL_INTERVAL = 0.05
DEFAULT_TIMEOUT = 5.0


def _start_child(temp_root: pathlib.Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(CHILD_SCRIPT)],
        env=isolated_temp_env(temp_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _read_ready_line(proc: subprocess.Popen[str]) -> int:
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if not line.startswith("READY "):
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        raise AssertionError(f"unexpected child output {line!r}, stderr={stderr!r}")
    return int(line.removeprefix("READY "))


def _wait_until_process_gone(pid: int, timeout: float = DEFAULT_TIMEOUT) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_is_running(pid):
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"process {pid} did not exit within {timeout}s")


def _wait_until_temp_clean(
    temp_root: pathlib.Path,
    before: list[dict],
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        after = list_wandb_temp_entries(temp_root)
        try:
            assert_no_new_wandb_entries(before, after, kinds={"dir"})
            return
        except AssertionError:
            time.sleep(POLL_INTERVAL)
    after = list_wandb_temp_entries(temp_root)
    assert_no_new_wandb_entries(before, after, kinds={"dir"})


def _terminate_child(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=1)


def test_temp_dir_cleanup_on_sigterm_to_core(tmp_path: pathlib.Path) -> None:
    isolated_temp = tmp_path / "temp"
    isolated_temp.mkdir()
    before = list_wandb_temp_entries(isolated_temp)

    proc = _start_child(isolated_temp)
    try:
        core_pid = _read_ready_line(proc)
        assert process_is_running(core_pid)

        os.kill(core_pid, signal.SIGTERM)
        _wait_until_process_gone(core_pid)
        _wait_until_temp_clean(isolated_temp, before)
    finally:
        _terminate_child(proc)


def test_temp_dir_cleanup_on_parent_death(tmp_path: pathlib.Path) -> None:
    isolated_temp = tmp_path / "temp"
    isolated_temp.mkdir()
    before = list_wandb_temp_entries(isolated_temp)

    proc = _start_child(isolated_temp)
    try:
        core_pid = _read_ready_line(proc)
        assert process_is_running(core_pid)

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=1)

        _wait_until_process_gone(core_pid)
        _wait_until_temp_clean(isolated_temp, before)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=1)
