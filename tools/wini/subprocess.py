"""Wrappers around `subprocess` for wini that print debug info."""

import os
import pathlib
import subprocess
from typing import Dict, Optional, Sequence, Union

from . import print


def check_call(
    cmd: Sequence[Union[str, pathlib.PurePath]],
    *,
    cwd: Optional[Union[str, pathlib.PurePath]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> None:
    """Invokes `subprocess.check_call`.

    Args:
        cmd: The command to run.
        cwd: The directory in which to run the command.
        extra_env: Environment variables to use for the command.
    """
    if cwd:
        print.info(f"In directory '{cwd}', running")
    else:
        print.info("Running")

    print.command([str(part) for part in cmd], env=extra_env)

    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
    else:
        env = None

    subprocess.check_call(
        cmd,
        cwd=cwd,
        env=env,
    )


def run(
    cmd: Sequence[Union[str, pathlib.PurePath]],
    extra_env: Optional[Dict[str, str]],
) -> None:
    """Invokes `subprocess.run`.

    Args:
        cmd: The command to run.
        extra_env: Environment variables to use for the command.
    """
    print.info("Running")
    print.command([str(part) for part in cmd])

    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
    else:
        env = None

    subprocess.run(cmd, env=env)
