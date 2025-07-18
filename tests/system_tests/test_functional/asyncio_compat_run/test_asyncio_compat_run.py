import pathlib
import signal
import subprocess


def test_asyncio_compat_run_stops_on_keyboard_interrupt():
    script = pathlib.Path(__file__).parent / "pass_if_cancelled.py"
    proc = subprocess.Popen(
        ["python", str(script)],
        stdout=subprocess.PIPE,
    )

    # Wait for process to enter the asyncio loop, then send SIGINT.
    assert proc.stdout.readline() == b"TEST READY\n"
    proc.send_signal(signal.SIGINT)

    assert proc.wait() == 0
