"""redirect tests"""

import os
import re
import sys
import time

import numpy as np
import pytest
import tqdm
import wandb

impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
if os.name != "nt":
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)


class CapList(list):
    def append(self, x):
        if not x:
            return
        lines = re.split(b"\r\n|\n", x)
        if len(lines) > 1:
            [self.append(line) for line in lines]
            return
        if x.startswith(b"\r"):
            if self:
                self.pop()
            x = x[1:]
        for sep in [b"\r\n", b"\n"]:
            if x.endswith(sep):
                x = x[: -len(sep)]
        super().append(x)


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
        for _ in tqdm.tqdm(range(10)):
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


@pytest.mark.parametrize("cls", impls)
@pytest.mark.timeout(5)
def test_print_torch_model(cls, capfd):
    # https://github.com/wandb/wandb/issues/2097
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
