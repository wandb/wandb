import pathlib
import subprocess

import pytest


@pytest.mark.wandb_core_only(reason="does not depend on service")
def test_wb_logging_last_resort():
    script = pathlib.Path(__file__).parent / "last_resort.py"

    output = subprocess.check_output(
        ["python", str(script)],
        stderr=subprocess.STDOUT,
    ).splitlines()

    assert output == [
        b"lastResort (before configuring)",
        b"stream handler (after configuring)",
    ]
