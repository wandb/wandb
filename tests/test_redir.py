"""redirect tests"""


from __future__ import print_function
import pytest
import sys
import os
import wandb
import numpy as np
import time
import tqdm


impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
if os.name != "nt":
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)


class CapList(list):
    def append(self, x):
        if not x:
            return
        sep = os.linesep.encode()
        if sep in x:
            for line in x.split(sep):
                self.append(line)
            return
        if x.startswith(b"\r"):
            if self:
                self.pop()
            x = x[1:]
        if x.endswith(sep):
            x = x[:-len(sep)]
        super(CapList, self).append(x)


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
        print("\x1b[31mHello\x1b[39m")  # [red]Hello[default]
        r.uninstall()
        assert o == [b"\x1b[91mHello"]


@pytest.mark.parametrize("cls", impls)
def test_interactive(cls, capfd):
    with capfd.disabled():
        r = cls("stdout", [lambda _: None])
        r.install()
        # TODO
        r.uninstall()


@pytest.mark.skipif(sys.version_info >= (3, 9), reason="Tensorflow not available")
@pytest.mark.parametrize("cls", impls)
def test_keras_progbar(cls, capfd):
    import tensorflow as tf

    with capfd.disabled():
        o = CapList()
        r = wandb.wandb_sdk.lib.redirect.Redirect("stdout", [o.append])
        model = tf.keras.models.Sequential()
        model.add(tf.keras.layers.Dense(10, input_dim=10))
        model.compile(loss="mse", optimizer="sgd")
        r.install()
        epochs = 5
        model.fit(np.zeros((10000, 10)), np.ones((10000, 10)), epochs=epochs)
        r.uninstall()
        assert len(o) == epochs * 2
