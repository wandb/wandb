"""
settings test.
"""

import pytest  # type: ignore

from . import wandb_summary
import copy


def test_attrib_get():
    s = wandb_summary.Summary()
    s.this = 2
    assert s.this == 2
