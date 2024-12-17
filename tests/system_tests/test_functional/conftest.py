import os
import pathlib
import runpy
import subprocess
import sys
from typing import Any
from unittest import mock

import pytest


@pytest.fixture
def execute_script():
    """Execute a script in the current interpreter using runpy.

    This fixture is a function that accepts the script's path and a list of
    arguments to pass to it, as if invoking it on the command line. The script
    runs with `__name__ == "__main__"`.
    """

    def helper(script_path: pathlib.Path, *args: Any) -> None:
        sys_argv = [str(script_path)] + list(args)

        with mock.patch("sys.argv", sys_argv):
            # runpy.run_path executes the script with the specified `run_name`.
            # By using `run_name="__main__"`, we simulate the script being
            # executed as if it were the main entry point, like running
            # `python script.py`.
            runpy.run_path(str(script_path), run_name="__main__")

    return helper


@pytest.fixture
def check_call_script():
    """Run a Python script in a new interpreter.

    This is a replacement for `subprocess.check_call(["python", ...])`.
    It calls the script and raises an error if its exit code is nonzero.

    The PYTHONPATH is set to the current `sys.path`, so that the script imports
    the same modules as the current interpreter.
    """

    def helper(script_path: pathlib.Path) -> None:
        subprocess.check_call(
            ["python", str(script_path)],
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(sys.path),
            },
        )

    return helper
