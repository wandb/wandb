import os
import time
from unittest import mock

import numpy as np
import pytest
import tqdm
import wandb
import wandb.sdk.lib.redirect
import wandb.util
from click.testing import CliRunner
from wandb.cli import cli

console_modes = ["wrap"]
if os.name != "nt":
    console_modes.append("redirect")


@pytest.mark.parametrize("console", console_modes)
def test_run_with_console_redirect(wandb_init, capfd, console):
    with capfd.disabled():
        run = wandb_init(settings={"console": console})

        print(np.random.randint(64, size=(40, 40, 40, 40)))

        for _ in tqdm.tqdm(range(100)):
            time.sleep(0.02)

        print("\n" * 1000)
        print("---------------")
        time.sleep(1)
        run.finish()


@pytest.mark.parametrize("console", console_modes)
def test_offline_compression(wandb_init, capfd, console):
    # map to old style wrap implementation until test is refactored
    if console == "wrap":
        console = "wrap_emu"
    with capfd.disabled():

        run = wandb_init(settings={"console": console, "mode": "offline"})
        run_dir, run_id = run.dir, run.id

        for _ in tqdm.tqdm(range(100), ncols=139, ascii=" 123456789#"):
            time.sleep(0.05)

        print("\n" * 1000)

        print("QWERT")
        print("YUIOP")
        print("12345")

        print("\x1b[A\r\x1b[J\x1b[A\r\x1b[1J")

        time.sleep(2)
        run.finish()

        binary_log_file = (
            os.path.join(os.path.dirname(run_dir), "run-" + run_id) + ".wandb"
        )
        binary_log = (
            CliRunner()
            .invoke(cli.sync, ["--view", "--verbose", binary_log_file])
            .stdout
        )

        # Only a single output record per stream is written when the run finishes
        assert binary_log.count("Record: output") == 2

        # Only final state of progress bar is logged
        assert binary_log.count("#") == 100, binary_log.count

        # Intermediate states are not logged
        assert "QWERT" not in binary_log
        assert "YUIOP" not in binary_log
        assert "12345" not in binary_log
        assert "UIOP" in binary_log


@pytest.mark.parametrize("console", console_modes)
@pytest.mark.parametrize("numpy", [True, False])
@pytest.mark.timeout(300)
def test_very_long_output(wandb_init, capfd, console, numpy):
    # https://wandb.atlassian.net/browse/WB-5437
    with capfd.disabled():
        with mock.patch.object(
            wandb.wandb_sdk.lib.redirect,
            "np",
            wandb.sdk.lib.redirect._Numpy() if not numpy else np,
        ):
            run = wandb_init(
                settings={
                    "console": console,
                    "mode": "offline",
                    "run_id": wandb.util.generate_id(),
                }
            )
            run_dir, run_id = run.dir, run.id
            print("LOG" * 1000000)
            print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m" * 100)
            print("===finish===")
            time.sleep(5)
            run.finish()

            binary_log_file = (
                os.path.join(os.path.dirname(run_dir), "run-" + run_id) + ".wandb"
            )
            binary_log = (
                CliRunner()
                .invoke(cli.sync, ["--view", "--verbose", binary_log_file])
                .stdout
            )

            assert "\\033[31m\\033[40m\\033[1mHello" in binary_log
            assert binary_log.count("LOG") == 1000000
            assert "===finish===" in binary_log


@pytest.mark.parametrize("console", console_modes)
def test_no_numpy(wandb_init, capfd, console):
    with capfd.disabled():
        with mock.patch.object(
            wandb.wandb_sdk.lib.redirect,
            "np",
            wandb.sdk.lib.redirect._Numpy(),
        ):
            run = wandb_init(settings={"console": console})
            print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m")
            run.finish()
            binary_log_file = (
                os.path.join(os.path.dirname(run.dir), "run-" + run.id) + ".wandb"
            )
            _ = (
                CliRunner()
                .invoke(cli.sync, ["--view", "--verbose", binary_log_file])
                .stdout
            )


@pytest.mark.parametrize("console", console_modes)
def test_memory_leak2(wandb_init, capfd, console):
    # map to old style wrap implementation until test is refactored
    if console == "wrap":
        console = "wrap_emu"
    with capfd.disabled():
        run = wandb_init(settings={"console": console})
        for _ in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
        run.finish()
