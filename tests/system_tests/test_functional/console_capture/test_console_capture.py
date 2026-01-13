import pathlib
import subprocess


def test_deadlocks():
    script = pathlib.Path(__file__).parent / "deadlocks.py"
    subprocess.check_call(["python", str(script)], timeout=5)


def test_infinite_loop():
    script = pathlib.Path(__file__).parent / "infinite_loop.py"
    subprocess.check_call(["python", str(script)], timeout=5)


def test_patch_stdout_and_stderr():
    script = pathlib.Path(__file__).parent / "patch_stdout_and_stderr.py"

    proc = subprocess.Popen(
        ["python", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    exit_code = proc.wait()  # on error, stderr may have useful details
    assert proc.stderr and proc.stdout
    assert proc.stderr.read() == b"I AM STDERR\n"
    assert proc.stdout.read() == b"I AM STDOUT\n"
    assert exit_code == 0


def test_patching_exception():
    script = pathlib.Path(__file__).parent / "patching_exception.py"
    subprocess.check_call(["python", str(script)])


def test_removes_callback_on_error():
    script = pathlib.Path(__file__).parent / "removes_callback_on_error.py"
    subprocess.check_call(["python", str(script)])


def test_uncapturing():
    script = pathlib.Path(__file__).parent / "uncapturing.py"
    subprocess.check_call(["python", str(script)])
