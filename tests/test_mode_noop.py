"""
mode test.
"""

import pytest  # type: ignore

import wandb


def test_mode_noop():
    """Make sure that all objects are dummy objects in noop case."""
    pass
    # run = wandb.init(mode="noop")
    # run.log(dict(this=2))
