import pathlib
import subprocess


def test_wb_logging_last_resort():
    script = pathlib.Path(__file__).parent / "last_resort.py"

    output = subprocess.check_output(
        ["python", str(script)],
        stderr=subprocess.STDOUT,
    ).splitlines()

    # Trim initial lines, which may include 3rd party warnings
    # depending on versions of installed packages.
    assert output[-2:] == [
        b"lastResort (before configuring)",
        b"stream handler (after configuring)",
    ]
