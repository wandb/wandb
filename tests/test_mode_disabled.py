"""
disabled mode test.
"""

from __future__ import division

import pytest  # type: ignore

import wandb
import pickle
import os


def test_disabled_noop():
    """Make sure that all objects are dummy objects in noop case."""
    run = wandb.init(mode="disabled")
    run.log(dict(this=2))
    run.finish()


def test_disabled_ops():
    run = wandb.init(mode="disabled")
    print(len(run))
    print(abs(run))
    print(~run)
    print(run + 10)
    print(run - 10)
    print(run * 10)
    print(run / 1.2)
    print(run // 10)
    print(run % 10)
    print(run ** 10)
    print(run << 10)
    print(run >> 10)
    print(run & 2)
    print(run ^ 2)
    print(run | 2)
    print(+run)
    print(-run)
    run += 1
    run -= 1
    run *= 1
    run /= 1.2
    run //= 1
    run **= 1
    run <<= 1
    run >>= 1
    run |= 1
    run %= 1
    run ^= 1
    run &= 1
    run()
    print(run.attrib)
    print(run["item"])
    run["3"] = 3
    print(run["3"])
    print(run[3])
    print(int(run))
    print(float(run))
    print(run < 2)
    print(run <= 2)
    print(run == 2)
    print(run > 2)
    print(run >= 2)
    print(run != 2)
    print(run)
    print(str(run))
    print(repr(run))
    if run:
        print(run)
    print(bool(run))


def test_disabled_summary():
    run = wandb.init(mode="disabled")
    run.summary["cat"] = 2
    run.summary["nested"] = dict(level=3)
    print(run.summary["cat"])
    print(run.summary.cat)
    with pytest.raises(KeyError):
        print(run.summary["dog"])
    run.summary["nested"]["level"] = 3


def test_disabled_can_pickle():
    """Will it pickle?"""
    # This case comes up when using wandb in disabled mode, with keras
    # https://wandb.atlassian.net/browse/WB-3981
    obj = wandb.wandb_sdk.lib.RunDisabled()
    with open("test.pkl", "wb") as file:
        pickle.dump(obj, file)
    os.remove("test.pkl")
