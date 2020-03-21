"""
history test.
"""

import pytest  # type: ignore

from . import wandb_history


class MockCallback(object):
    def __init__(self):
        self.row = None

    def callback(self, row=None):
        self.row = row


def test_row_add():
    m = MockCallback()
    h = wandb_history.History()
    h._set_callback(m.callback)
    h._row_add(dict(this=2))
    assert m.row == dict(this=2, _step=0)


def test_row_update():
    m = MockCallback()
    h = wandb_history.History()
    h._set_callback(m.callback)
    h._row_update(dict(this=2))
    assert m.row == None
