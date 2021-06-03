"""redirect tests"""


from __future__ import print_function

from wandb.cli import cli

import pytest
import sys
import os
import wandb
import numpy as np
import re
import time
import tqdm


impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
console_modes = ["wrap"]
if os.name != "nt":
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)
    console_modes.append("redirect")


class CapList(list):
    def append(self, x):
        if not x:
            return
        lines = re.split(b"\r\n|\n", x)
        if len(lines) > 1:
            [self.append(l) for l in lines]
            return
        if x.startswith(b"\r"):
            if self:
                self.pop()
            x = x[1:]
        for sep in [b"\r\n", b"\n"]:
            if x.endswith(sep):
                x = x[: -len(sep)]
        super(CapList, self).append(x)


@pytest.fixture
def console_settings(test_settings, request):
    s = wandb.Settings(console=request.param)
    test_settings._apply_settings(s)
    return test_settings


@pytest.mark.parametrize("cls", impls)
def test_basic(cls, capfd):
    with capfd.disabled():
        out = CapList()
        redir = cls("stdout", cbs=[out.append])
        redir.install()
        print("Test")
        redir.uninstall()
        assert out == [b"Test"]


@pytest.mark.parametrize("cls", impls)
def test_reinstall(cls, capfd):
    with capfd.disabled():
        o1, o2 = CapList(), CapList()
        r1 = cls("stdout", cbs=[o1.append])
        r2 = cls("stdout", cbs=[o2.append])
        r1.install()
        print("ABCD")
        r2.install()
        print("WXYZ")
        r1.install()
        print("1234")
        r2.install()
        print("5678")
        r2.uninstall()
        assert o1 == [b"ABCD", b"1234"]
        assert o2 == [b"WXYZ", b"5678"]


@pytest.mark.parametrize("cls", impls)
def test_tqdm_progbar(cls, capfd):
    with capfd.disabled():
        o = CapList()
        r = cls("stderr", cbs=[o.append])
        r.install()
        for i in tqdm.tqdm(range(10)):
            time.sleep(0.1)
        r.uninstall()
        assert len(o) == 1 and o[0].startswith(b"100%")


@pytest.mark.parametrize("cls", impls)
def test_formatting(cls, capfd):
    with capfd.disabled():
        o = CapList()
        r = cls("stdout", cbs=[o.append])
        r.install()
        print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m")
        r.uninstall()
        assert o == [b"\x1b[31m\x1b[40m\x1b[1mHello"]


@pytest.mark.parametrize("cls", impls)
def test_cursor(cls, capfd):
    with capfd.disabled():
        o = CapList()
        r = cls("stdout", cbs=[o.append])
        r.install()
        s = "ABCD\nEFGH\nIJKX\nMNOP"
        s += "\x1b[1A"
        s += "\x1b[1D"
        s += "L"
        s += "\x1b[1B"
        s += "\r"
        s += "\x1b[K"
        s += "QRSD"
        s += "\x1b[1D"
        s += "\x1b[1C"
        s += "\x1b[1D"
        s += "T"
        s += "\x1b[4A"
        s += "\x1b[1K"
        s += "\r"
        s += "1234"
        s += "\x1b[4B"
        s += "\r"
        s += "WXYZ"
        s += "\x1b[2K"
        print(s)
        r.uninstall()
        assert o == [b"1234", b"EFGH", b"IJKL", b"QRST"]


@pytest.mark.parametrize("cls", impls)
def test_erase_screen(cls, capfd):
    with capfd.disabled():
        o = CapList()
        r = cls("stdout", cbs=[o.append])
        r.install()
        s = "QWERT\nYUIOP\n12345"
        s += "\r"
        s += "\x1b[J"
        s += "\x1b[A"
        s += "\r"
        s += "\x1b[1J"
        print(s)
        r.uninstall()
        assert o == [b" UIOP"]
        o = CapList()
        r = cls("stdout", cbs=[o.append])
        r.install()
        print("QWERT\nYUIOP\n12345")
        print("\x1b[2J")
        r.uninstall()
        assert o == []


@pytest.mark.parametrize("cls", impls)
def test_interactive(cls, capfd):
    with capfd.disabled():
        r = cls("stdout", [lambda _: None])
        r.install()
        # TODO
        r.uninstall()


@pytest.mark.skipif(sys.version_info >= (3, 9), reason="Tensorflow not available.")
@pytest.mark.skipif(
    not sys.stdout.isatty(), reason="Keras won't show progressbar on non tty terminal."
)
@pytest.mark.parametrize("cls", impls)
def test_keras_progbar(cls, capfd):
    import tensorflow as tf

    with capfd.disabled():
        o = CapList()
        r = cls("stdout", [o.append])
        model = tf.keras.models.Sequential()
        model.add(tf.keras.layers.Dense(10, input_dim=10))
        model.compile(loss="mse", optimizer="sgd")
        r.install()
        epochs = 5
        model.fit(np.zeros((10000, 10)), np.ones((10000, 10)), epochs=epochs)
        r.uninstall()
        assert len(o) in (epochs * 2, epochs * 2 + 1)  # Allow 1 offs


@pytest.mark.parametrize("cls", impls)
def test_numpy(cls, capfd):
    with capfd.disabled():
        r = cls("stdout", [lambda _: None])
        r.install()
        print(np.random.randint(64, size=(40, 40, 40, 40)))
        r.uninstall()


@pytest.mark.skipif(
    sys.version_info >= (3, 9) or sys.version_info < (3, 5),
    reason="Torch not available.",
)
@pytest.mark.parametrize("cls", impls)
@pytest.mark.timeout(5)
def test_print_torch_model(cls, capfd):
    # https://github.com/wandb/client/issues/2097
    import torch

    with capfd.disabled():
        r = cls("stdout", [lambda _: None])
        model = torch.nn.ModuleList(
            torch.nn.Conv2d(1, 1, 1, bias=False) for _ in range(1000)
        )
        start = time.time()
        print(model)
        end = time.time()
        t1 = end - start
        r.install()
        start = time.time()
        print(model)
        end = time.time()
        t2 = end - start
        overhead = t2 - t1
        assert overhead < 0.2
        r.uninstall()


@pytest.mark.parametrize("console_settings", console_modes, indirect=True)
def test_run_with_console_redirect(console_settings, capfd):
    with capfd.disabled():
        run = wandb.init(settings=console_settings)

        print(np.random.randint(64, size=(40, 40, 40, 40)))

        for i in tqdm.tqdm(range(100)):
            time.sleep(0.02)

        print("\n" * 1000)
        print("---------------")
        run.finish()


@pytest.mark.parametrize("console_settings", console_modes, indirect=True)
def test_offline_compression(console_settings, capfd, runner):
    with capfd.disabled():
        s = wandb.Settings(mode="offline")
        console_settings._apply_settings(s)

        run = wandb.init(settings=console_settings)

        for i in tqdm.tqdm(range(100), ncols=139, ascii=" 123456789#"):
            time.sleep(0.05)

        print("\n" * 1000)

        print("QWERT")
        print("YUIOP")
        print("12345")

        print("\x1b[A\r\x1b[J\x1b[A\r\x1b[1J")

        time.sleep(1)

        run.finish()
        binary_log_file = (
            os.path.join(os.path.dirname(run.dir), "run-" + run.id) + ".wandb"
        )
        binary_log = runner.invoke(
            cli.sync, ["--view", "--verbose", binary_log_file]
        ).stdout

        # Only a single output record per stream is written when the run finishes
        assert binary_log.count("Record: output") == 2

        # Only final state of progress bar is logged
        assert binary_log.count("#") == 100, binary_log.count

        # Intermediete states are not logged
        assert "QWERT" not in binary_log
        assert "YUIOP" not in binary_log
        assert "12345" not in binary_log
        assert "UIOP" in binary_log


@pytest.mark.parametrize("console_settings", console_modes, indirect=True)
@pytest.mark.parametrize("numpy", [True, False])
@pytest.mark.timeout(120)
def test_very_long_output(console_settings, capfd, runner, numpy):
    # https://wandb.atlassian.net/browse/WB-5437
    with capfd.disabled():
        if not numpy:
            wandb.wandb_sdk.lib.redirect.np = wandb.wandb_sdk.lib.redirect._Numpy()
        try:
            run = wandb.init(settings=console_settings)
            print("LOG" * 1000000)
            print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m" * 100)
            print("===finish===")
            run.finish()
            binary_log_file = (
                os.path.join(os.path.dirname(run.dir), "run-" + run.id) + ".wandb"
            )
            binary_log = runner.invoke(
                cli.sync, ["--view", "--verbose", binary_log_file]
            ).stdout
            assert "\\033[31m\\033[40m\\033[1mHello" in binary_log
            assert binary_log.count("LOG") == 1000000
            assert "===finish===" in binary_log
        finally:
            wandb.wandb_sdk.lib.redirect.np = np


@pytest.mark.parametrize("console_settings", console_modes, indirect=True)
def test_no_numpy(console_settings, capfd, runner):
    with capfd.disabled():
        wandb.wandb_sdk.lib.redirect.np = wandb.wandb_sdk.lib.redirect._Numpy()
        try:
            run = wandb.init(settings=console_settings)
            print("\x1b[31m\x1b[40m\x1b[1mHello\x01\x1b[22m\x1b[39m")
            run.finish()
            binary_log_file = (
                os.path.join(os.path.dirname(run.dir), "run-" + run.id) + ".wandb"
            )
            binary_log = runner.invoke(
                cli.sync, ["--view", "--verbose", binary_log_file]
            ).stdout
        finally:
            wandb.wandb_sdk.lib.redirect.np = np


@pytest.mark.parametrize("console_settings", console_modes, indirect=True)
def test_memory_leak2(console_settings, capfd, runner):
    with capfd.disabled():
        run = wandb.init(settings=console_settings)
        for i in range(1000):
            print("ABCDEFGH")
        time.sleep(3)
        assert len(run._out_redir._emulator.buffer) < 1000
        run.finish()
