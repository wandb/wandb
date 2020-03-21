"""
settings test.
"""

import pytest  # type: ignore

from . import wandb_summary


class MockCallback(object):
    def __init__(self):
        self.key = None
        self.val = None
        self.data = None

    def callback(self, key=None, val=None, data=None):
        self.key = key
        self.val = val
        self.data = data


def test_attrib_get():
    s = wandb_summary.Summary()
    s['this'] = 2
    assert s.this == 2


def test_item_get():
    s = wandb_summary.Summary()
    s['this'] = 2
    assert s['this'] == 2


def test_attrib_internal_callback():
    m = MockCallback()
    s = wandb_summary.Summary()
    s._set_callback(m.callback)
    s['this'] = 2
    assert m.key == 'this'
    assert m.val == 2
    assert m.data == dict(this=2)
