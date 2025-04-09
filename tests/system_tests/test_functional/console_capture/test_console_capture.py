import pathlib
import subprocess

import pytest


@pytest.mark.wandb_core_only(reason="Test does not depend on service process.")
def test_patch_stdout_and_stderr():
    script = pathlib.Path(__file__).parent / "patch_stdout_and_stderr.py"

    proc = subprocess.Popen(
        ["python", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    exit_code = proc.wait()  # on error, stderr may have useful details
    assert proc.stderr.read() == b"I AM STDERR\n"
    assert proc.stdout.read() == b"I AM STDOUT\n"
    assert exit_code == 0


@pytest.mark.wandb_core_only(reason="Test does not depend on service process.")
def test_patching_exception():
    script = pathlib.Path(__file__).parent / "patching_exception.py"

    subprocess.check_call(["python", str(script)])


@pytest.mark.wandb_core_only(reason="Test does not depend on service process.")
def test_uncapturing():
    script = pathlib.Path(__file__).parent / "uncapturing.py"

    subprocess.check_call(["python", str(script)])
