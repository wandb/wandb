import os
import re
import time
from unittest import mock

import pytest
import tqdm
import wandb
import wandb.sdk.lib.redirect
import wandb.util
from click.testing import CliRunner
from wandb.cli import cli
from wandb.sdk.lib import runid


def _wait_for_legacy_service_transaction_log():
    """Wait to allow for legacy-service to write the transaction log file.

    When legacy-service receives a shutdown request initiated by `run.finish()`,
    it sets an internal Event and responds immediately. The writer thread has
    a loop similar to this:

        while not event.is_set():
            try:
                record = self._input_q.get(timeout=1)
            except queue.Empty:
                continue
            self._process(record)

        self._finish()

    After the event is set, it may be an entire second before
    `input_q.get(timeout=1)` times out and `self._finish()` is invoked.
    The writer thread's `self._finish()` flushes the transaction log file,
    which is completely in-memory until this point in these tests.

    Within that time, the test's `run.finish()` or Run context manager returns.
    If the test tries to read the transaction log file too quickly, it observes
    an empty file and fails.

    NOTE: Prior to https://github.com/wandb/wandb/pull/9469, this sleep was
    not entirely necessary because of another 1-second wait in the client itself
    that followed a similar pattern as the above. Tests used to put a sleep
    before `run.finish()`, likely to allow the writer thread to process
    any buffered records if the CI worker is slow.
    """
    time.sleep(2)


@pytest.mark.skipif(
    os.name == "nt",
    reason="redirect mode does not work on Windows",
)
@pytest.mark.skip_wandb_core(reason="redirect mode not implemented in core")
def test_console_redirect(wandb_backend_spy, capfd):
    with capfd.disabled():
        with wandb.init(settings={"console": "redirect"}) as run:
            # Write directly to the stdout file descriptor.
            with open(1, mode="wb", closefd=False) as stdout:
                stdout.write(b"Testing...\n")
                stdout.write(b"abc")

                # Check that terminal emulation is used:
                stdout.write(b"\rxyz")  # replace abc by xyz
                stdout.write(b"\x1b[A\rV")  # replace T in testing by V

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        assert 0 in output
        assert 1 in output
        assert "Vesting..." in output[0]
        assert "xyz" in output[1]
        assert "abc" not in output[1]


def test_console_wrap_raw(wandb_backend_spy):
    with wandb.init(settings={"console": "wrap_raw"}) as run:
        print("Testing...")
        print("abc", end="")
        print("\rxyz", end="")
        print("\x1b[A\rV", end="")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        assert 0 in output
        assert 1 in output
        assert "Vesting..." in output[0]
        assert "xyz" in output[1]
        assert "abc" not in output[1]


@pytest.mark.skip_wandb_core(reason="wrap_emu mode not implemented in core")
def test_console_wrap_emu(wandb_backend_spy):
    with wandb.init(settings={"console": "wrap_emu"}) as run:
        print("Testing...")
        print("abc", end="")
        print("\rxyz", end="")
        print("\x1b[A\rV", end="")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        assert 0 in output
        assert 1 in output
        assert "Vesting..." in output[0]
        assert "xyz" in output[1]
        assert "abc" not in output[1]


def test_offline_compression(user):
    with wandb.init(settings={"console": "wrap_emu", "mode": "offline"}) as run:
        run_dir, run_id = run.dir, run.id

        for _ in tqdm.tqdm(range(100), ncols=139, ascii=" 123456789#"):
            time.sleep(0.05)

        print("\n" * 1000)

        print("QWERT")
        print("YUIOP")
        print("12345")

        print("\x1b[A\r\x1b[J\x1b[A\r\x1b[1J")

    _wait_for_legacy_service_transaction_log()

    binary_log_file = os.path.join(os.path.dirname(run_dir), "run-" + run_id) + ".wandb"
    binary_log = (
        CliRunner().invoke(cli.sync, ["--view", "--verbose", binary_log_file]).stdout
    )

    # Only a single output record per stream is written when the run finishes
    re_output = re.compile(r"^Record: num: \d+\noutput {", flags=re.MULTILINE)
    assert len(re_output.findall(binary_log)) == 2

    # Only final state of progress bar is logged
    assert binary_log.count("#") == 100, binary_log.count

    # Intermediate states are not logged
    assert "QWERT" not in binary_log
    assert "YUIOP" not in binary_log
    assert "12345" not in binary_log
    assert "UIOP" in binary_log


@pytest.mark.timeout(300)
def test_very_long_output(user):
    # https://wandb.atlassian.net/browse/WB-5437
    with wandb.init(
        settings={
            # To test the TerminalEmulator, we do not use "wrap_raw".
            "console": "wrap_emu",
            "mode": "offline",
            "run_id": runid.generate_id(),
        }
    ) as run:
        run_dir, run_id = run.dir, run.id
        print("LOG" * 1000000)
        print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m" * 100)
        print("===finish===")

    _wait_for_legacy_service_transaction_log()

    binary_log_file = os.path.join(os.path.dirname(run_dir), "run-" + run_id) + ".wandb"
    binary_log = (
        CliRunner().invoke(cli.sync, ["--view", "--verbose", binary_log_file]).stdout
    )

    assert "\\033[31m\\033[40m\\033[1mHello" in binary_log
    assert binary_log.count("LOG") == 1000000
    assert "===finish===" in binary_log


@pytest.mark.skip_wandb_core(reason="wrap_emu mode not implemented in core")
def test_no_numpy(wandb_backend_spy):
    with mock.patch.object(
        wandb.wandb_sdk.lib.redirect,
        "np",
        wandb.sdk.lib.redirect._Numpy(),
    ):
        # Use "wrap_emu" to make sure TerminalEmulator's usage of _Numpy works.
        with wandb.init(settings={"console": "wrap_emu"}) as run:
            print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)

        assert 0 in output
        assert "\x1b[31m\x1b[40m\x1b[1mHello" in output[0]


def test_memory_leak2(user):
    # This appears to test this:
    #   https://github.com/wandb/wandb/pull/2111/files#r640819752
    with wandb.init(settings={"console": "wrap_emu"}) as run:
        for _ in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
