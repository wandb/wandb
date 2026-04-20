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


def test_write_logs_appears_in_output(wandb_backend_spy):
    """run.write_logs() sends text through the OutputLoggerRecord pipeline."""
    with wandb.init() as run:
        run.write_logs("my custom log line")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        lines = list(output.values())
        assert any("my custom log line" in line for line in lines)


def test_write_logs_works_with_console_off(wandb_backend_spy):
    """run.write_logs() works even when console capture is disabled."""
    with wandb.init(settings={"console": "off"}) as run:
        run.write_logs("still captured")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        lines = list(output.values())
        assert any("still captured" in line for line in lines)


def test_write_logs_and_print_ordered_with_console_on(wandb_backend_spy):
    """When console capture is on, write_logs and print output are ordered by time."""
    with wandb.init(settings={"console": "wrap_raw"}) as run:
        print("print-first")
        time.sleep(0.1)
        run.write_logs("log-second")
        time.sleep(0.1)
        print("print-third")
        time.sleep(0.1)
        run.write_logs("log-fourth")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        # output is a dict of {line_number: content}, sorted by line number
        lines = [v for _, v in sorted(output.items())]
        combined = "\n".join(lines)

        idx_first = combined.find("print-first")
        idx_second = combined.find("log-second")
        idx_third = combined.find("print-third")
        idx_fourth = combined.find("log-fourth")

        assert idx_first != -1, "print-first not found in output"
        assert idx_second != -1, "log-second not found in output"
        assert idx_third != -1, "print-third not found in output"
        assert idx_fourth != -1, "log-fourth not found in output"

        assert idx_first < idx_second < idx_third < idx_fourth


def test_wandb_logger_handler_integration(wandb_backend_spy):
    """WandbLoggerHandler routes Python logger output to the Logs tab."""
    import logging

    from wandb.sdk.lib.logger_capture import WandbLoggerHandler

    with wandb.init() as run:
        handler = WandbLoggerHandler(run, level=logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger = logging.getLogger("test_handler_integration")
        logger.addHandler(handler)
        try:
            logger.info("handler integration test")
        finally:
            logger.removeHandler(handler)

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        lines = list(output.values())
        assert any("handler integration test" in line for line in lines)


def test_memory_leak2(user):
    # This appears to test this:
    #   https://github.com/wandb/wandb/pull/2111/files#r640819752
    with wandb.init(settings={"console": "wrap_emu"}) as run:
        for _ in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
