"""redirect tests"""


from __future__ import print_function
import pytest
import os
import wandb
import time

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


