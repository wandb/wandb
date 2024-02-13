"""Wrappers around `subprocess` for wini that print debug info."""

import subprocess
from typing import List, Mapping, Optional

from . import print


def check_call(
    cmd: List[object],
    *,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """Invokes `subprocess.check_call`.

    Args:
        cmd: The command to run.
        cwd: The directory in which to run the command.
        env: Environment variables to use for the command.
    """
    if cwd:
        print.info(f"In directory '{cwd}', running")
    else:
        print.info("Running")

    print.command([str(part) for part in cmd])

    subprocess.check_call(
        cmd,
        cwd=cwd,
        env=env,
    )


def run(cmd: List[object]) -> None:
    """Invokes `subprocess.run`.

    Args:
        cmd: The command to run.
    """
    print.info("Running")
    print.command([str(part) for part in cmd])
    subprocess.run(cmd)
