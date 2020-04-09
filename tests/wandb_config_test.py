"""
config tests.
"""

from wandb import wandb_sdk


def callback_func(key, val, data):
    print(key, val, data)


def test_attrib_get():
    s = wandb_sdk.Config()
    s._set_callback(callback_func)
    s.this = 2
    assert s.this == 2


def test_locked_set():
    s = wandb_sdk.Config()
    s.update_locked(dict(this=2, that=4), "sweep")
    s.this = 8
    assert s.this == 2
