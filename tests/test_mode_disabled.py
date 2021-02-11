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
    print(run / 10)
    print(run // 10)
    print(run % 10)
    print(run ** 10)
    print(run << 10)
    print(run >> 10)
    print(run and True)
    print(run ^ 2)
    print(run or False)
    print(+run)
    print(-run)


def test_disabled_can_pickle():
    """Will it pickle?"""
    # This case comes up when using wandb in disabled mode, with keras
    # https://wandb.atlassian.net/browse/WB-3981
    obj = wandb.wandb_sdk.lib.RunDisabled()
    with open("test.pkl", "wb") as file:
        pickle.dump(obj, file)
    os.remove("test.pkl")
