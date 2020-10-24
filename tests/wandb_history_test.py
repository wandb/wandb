"""
history test.
"""

import pytest  # type: ignore

from wandb import wandb_sdk


class MockCallback(object):
    def __init__(self):
        self.row = None

    def callback(self, row=None, step=None):
        self.row = row


def test_row_add(mocked_run):
    m = MockCallback()
    h = wandb_sdk.History(mocked_run)
    h._set_callback(m.callback)
    h._row_add(dict(this=2))
    assert m.row["this"] == 2
    assert m.row["_step"] == 0


def test_row_update(mocked_run):
    m = MockCallback()
    h = wandb_sdk.History(mocked_run)
    h._set_callback(m.callback)
    h._row_update(dict(this=2))
    assert m.row is None
