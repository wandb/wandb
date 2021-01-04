"""redirect tests"""


from __future__ import print_function
import pytest
import os
import wandb
import time
import tqdm


impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
if os.name != 'nt':
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)


@pytest.mark.parametrize("cls", impls)
def test_basic(cls):
    out = []
    redir = cls("stdout", cbs=[out.append])
    redir.install()
    print("Test")
    redir.uninstall()
    assert out == [b"Test"]

@pytest.mark.parametrize("cls", impls)
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
    sep = os.linesep.encode()
    assert o1 == [b"ABCD" + sep + b"1234"]
    assert o2 == [b"WXYZ" + sep + b"5678"]

@pytest.mark.parametrize("cls", impls)
def test_progressbar(cls):
    o = []
    r = cls("stdout", cbs=[o.append])
    r.install()
    for i in tqdm.tqdm(range(10)):
        time.sleep(0.1)
    r.uninstall()
    print(o)

