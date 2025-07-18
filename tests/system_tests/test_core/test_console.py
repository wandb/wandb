import os
import re
import time

import pytest
import tqdm
import wandb
from click.testing import CliRunner
from wandb.cli import cli
from wandb.sdk.lib import runid


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

    binary_log_file = os.path.join(os.path.dirname(run_dir), "run-" + run_id) + ".wandb"
    binary_log = (
        CliRunner().invoke(cli.sync, ["--view", "--verbose", binary_log_file]).stdout
    )

    assert "\\033[31m\\033[40m\\033[1mHello" in binary_log
    assert binary_log.count("LOG") == 1000000
    assert "===finish===" in binary_log


def test_memory_leak2(user):
    # This appears to test this:
    #   https://github.com/wandb/wandb/pull/2111/files#r640819752
    with wandb.init(settings={"console": "wrap_emu"}) as run:
        for _ in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
