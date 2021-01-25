import sys
import os
import wandb
import numpy as np
import re
import time
import tqdm


impls = [wandb.wandb_sdk.lib.redirect.StreamWrapper]
if os.name != "nt":
    impls.append(wandb.wandb_sdk.lib.redirect.Redirect)


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


def test_basic(cls):
    out = CapList()
    redir = cls("stdout", cbs=[out.append])
    redir.install()
    print("Test")
    redir.uninstall()
    assert out == [b"Test"]

def test_formatting(cls):
    o = CapList()
    r = cls("stdout", cbs=[o.append])
    r.install()
    print("\x1b[31mHello\x1b[39m")  # [red]Hello[default]
    r.uninstall()
    return o, r
    assert o == [b"\x1b[31mHello"]