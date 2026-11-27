import logging
import time

import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


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


def test_write_logs_appears_in_output(wandb_backend_spy: WandbBackendSpy):
    """run.write_logs() sends text through the OutputLoggerRecord pipeline."""
    with wandb.init() as run:
        run.write_logs("my custom log line")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        lines = list(output.values())
        assert any("my custom log line" in line for line in lines)


def test_write_logs_works_with_console_off(wandb_backend_spy: WandbBackendSpy):
    """run.write_logs() works even when console capture is disabled."""
    with wandb.init(settings={"console": "off"}) as run:
        run.write_logs("still captured")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        lines = list(output.values())
        assert any("still captured" in line for line in lines)


def test_capture_loggers(wandb_backend_spy: WandbBackendSpy):
    """The capture_loggers setting captures logger output as specified."""
    logger1 = logging.getLogger(f"{__name__}:test_capture_loggers_1")
    logger1.setLevel(logging.INFO)
    logger2 = logging.getLogger(f"{__name__}:test_capture_loggers_2")
    logger2.setLevel(logging.INFO)
    settings = wandb.Settings(
        capture_loggers={
            logger1.name: "INFO",
            logger2.name: "ERROR",
        }
    )

    with wandb.init(settings=settings) as run:
        logger1.info("logger1 - INFO")
        logger2.info("logger2 - INFO")  # filtered out by level
        logger2.error("logger2 - ERROR")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        output_combined = "\n".join(
            f"{offset}: {line}" for offset, line in output.items()
        )

        assert "logger1 - INFO" in output_combined
        assert "logger2 - INFO" not in output_combined
        assert "logger2 - ERROR" in output_combined
        assert not logger1.handlers  # ensure handlers are cleaned up
        assert not logger2.handlers


def test_memory_leak2(user):
    # This appears to test this:
    #   https://github.com/wandb/wandb/pull/2111/files#r640819752
    with wandb.init(settings={"console": "wrap_emu"}) as run:
        for _ in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
