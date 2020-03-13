"""
config tests.
"""

import pytest  # type: ignore

from . import wandb_config


def test_attrib_get():
    s = wandb_config.Config()
    s.this = 2
    assert s.this == 2


def test_locked_set():
    s = wandb_config.Config()
    s.update_locked(dict(this=2, that=4), "sweep")
    s.this = 8
    assert s.this == 2

