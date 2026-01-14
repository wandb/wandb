import pathlib
import signal
import subprocess
import time


def test_interrupt_join():
    script = pathlib.Path(__file__).parent / "interrupt_join.py"
    proc = subprocess.Popen(
        ["python", str(script)],
        stdout=subprocess.PIPE,
    )
    assert proc.stdout

    # Wait for the process's main thread to enter join(), then send SIGINT.
    assert proc.stdout.readline() == b"TEST READY\n"
    time.sleep(0.01)  # Hope the main thread reaches the try-catch in join().
    proc.send_signal(signal.SIGINT)

    assert proc.wait() == 0


def test_interrupt_run():
    script = pathlib.Path(__file__).parent / "interrupt_run.py"
    proc = subprocess.Popen(
        ["python", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin
    assert proc.stdout

    # Wait for process to enter the first run(), then send SIGINT.
    assert proc.stdout.readline() == b"STARTED\n"
    time.sleep(0.01)  # Hope the main thread reaches the try-catch in run().
    proc.send_signal(signal.SIGINT)

    # The run() task should get cancelled, but other tasks should stay.
    assert proc.stdout.readline() == b"CANCELLED\n"
    proc.stdin.write(b"CONTINUE\n")
    proc.stdin.flush()
    assert proc.stdout.readline() == b"STILL GOOD\n"

    assert proc.wait() == 0


def test_does_not_block_exit():
    script = pathlib.Path(__file__).parent / "does_not_block_exit.py"
    result = subprocess.check_output(["python", str(script)])

    # On failure, the result will also include the string "FAIL".
    assert result == b""
