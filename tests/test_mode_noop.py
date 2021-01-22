"""
mode test.
"""

import pytest  # type: ignore

import wandb
import pickle
import os


def test_mode_noop():
    """Make sure that all objects are dummy objects in noop case."""
    pass
    # run = wandb.init(mode="noop")
    # run.log(dict(this=2))


def test_dummy_can_pickle():
    # This case comes up when using wandb in disabled mode, with keras
    # https://wandb.atlassian.net/browse/WB-3981
    obj = wandb.dummy.Dummy()
    with open("test.pkl", "wb") as file:
        pickle.dump(obj, file)
    os.remove("test.pkl")
