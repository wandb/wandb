"""Wrappers around `subprocess` for wini that print debug info."""

import pathlib
import subprocess
from typing import Mapping, Optional, Sequence, Union

from . import print


def check_call(
    cmd: Sequence[Union[str, pathlib.PurePath]],
    *,
    cwd: Optional[Union[str, pathlib.PurePath]] = None,
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


def run(cmd: Sequence[Union[str, pathlib.PurePath]]) -> None:
    """Invokes `subprocess.run`.

    Args:
        cmd: The command to run.
    """
    print.info("Running")
    print.command([str(part) for part in cmd])
    subprocess.run(cmd)
