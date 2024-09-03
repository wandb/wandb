import pathlib
import runpy
from unittest import mock

import pytest


@pytest.fixture
def execute_script():
    def helper(train_script_path: pathlib.Path):
        with mock.patch("sys.argv", [""]):
            runpy.run_path(str(train_script_path), run_name="__main__")

    return helper
