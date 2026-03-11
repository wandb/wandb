import pathlib
import subprocess


def test_wb_logging_last_resort():
    script = pathlib.Path(__file__).parent / "last_resort.py"

    output = subprocess.check_output(
        # Prevent warnings from 3rd party libraries from polluting the output.
        ["python", "-W", "ignore", str(script)],
        stderr=subprocess.STDOUT,
    ).splitlines()

    assert output == [
        b"lastResort (before configuring)",
        b"stream handler (after configuring)",
    ]
