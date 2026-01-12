from __future__ import annotations

import pathlib
import runpy
from typing import Any
from unittest import mock

import pytest


@pytest.fixture
def execute_script():
    # Define a helper function that will take in the script path and command-line arguments
    def helper(train_script_path: pathlib.Path, *args: Any) -> None:
        # sys_argv simulates the command-line arguments.
        sys_argv = [str(train_script_path)] + list(args)

        # Patch sys.argv to replace the real command-line arguments with our simulated ones.
        # This ensures that the target script sees the provided arguments when run.
        with mock.patch("sys.argv", sys_argv):
            # Execute the target script at `train_script_path` in a similar way
            # as if it was run directly from the command line.
            # runpy.run_path executes the script with the specified `run_name`.
            # By using `run_name="__main__"`, we simulate the script being executed
            # as if it were the main entry point, like running `python script.py`.
            runpy.run_path(str(train_script_path), run_name="__main__")

    return helper
