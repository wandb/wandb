
import pytest
import os
import wandb
import tensorflow as tf
import numpy as np
import time
import tqdm


impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
if os.name != "nt":
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)


def test_keras_progbar(cls):
    o = []
    r = wandb.wandb_sdk.lib.redirect.Redirect("stdout", [o.append])
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Dense(10, input_dim=10))
    model.compile(loss="mse", optimizer="sgd")
    r.install()
    epochs = 5
    model.fit(np.zeros((10000, 10)), np.ones((10000, 10)), epochs=epochs)
    r.uninstall()
    assert len(o) == 1
    assert len(o[0].split(os.linesep.encode())) == epochs * 2 + 1

def test_basic(cls):
    out = []
    redir = cls("stdout", cbs=[out.append])
    redir.install()
    print("Test")
    redir.uninstall()
    assert out == [b"Test\n"]

def test_reinstall(cls):
    o1, o2 = [], []
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
    assert o1 == [b"ABCD\n", b"1234\n"]
    assert o2 == [b"WXYZ\n", b"5678\n"]

def test_tqdm_progbar(cls):
    o = []
    r = cls("stderr", cbs=[o.append])
    r.install()
    for i in tqdm.tqdm(range(10)):
        time.sleep(0.1)
    r.uninstall()
    assert len(o) == 1 and o[0].startswith(b"100%|")


def test_formatting(cls):
    o = []
    r = cls("stdout", cbs=[o.append])
    r.install()
    print("\x1b[31mHello\x1b[39m")  # [red]Hello[default]
    r.uninstall()
    assert o == [b"\x1b[91mHello\n"], o

# import fastai
# from fastai.optimizer import Adam
# from fastai.data.core import DataLoader, DataLoaders
# from fastai.vision.all import Learner

# import wandb

# class DummyData(torch.utils.data.Dataset):

# 	def __len__(self):
# 		return 10000

# 	def __getitem__(self, i):
# 		return torch.randn(4), torch.randn(4)


# wandb.init(project='test', name='t1')

# net = nn.Linear(4, 4).cuda()

# ds = DummyData()
# dl = DataLoader(ds)

# data = DataLoaders(dl, dl).cuda()

# learn = Learner(data, net, opt_func=Adam, loss_func = torch.nn.MSELoss())

# learn.fit(10)