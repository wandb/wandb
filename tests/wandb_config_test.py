"""
config tests.
"""

import pytest
import yaml
from wandb import wandb_sdk


def callback_func(key=None, val=None, data=None):
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
    assert s.that == 4


def test_update():
    s = wandb_sdk.Config()
    s.update(dict(this=8))
    assert dict(s) == dict(this=8)
    s.update(dict(that=4))
    assert dict(s) == dict(this=8, that=4)


def test_setdefaults():
    s = wandb_sdk.Config()
    s.update(dict(this=8))
    assert dict(s) == dict(this=8)
    s.setdefaults(dict(thiss=2, that=4))
    assert dict(s) == dict(this=8, that=4)


def test_locked_update():
    s = wandb_sdk.Config()
    s.update_locked(dict(this=2, that=4), "sweep")
    s.update(dict(this=8))
    assert s.this == 2
    assert s.that == 4


def test_locked_no_sideeffect():
    s = wandb_sdk.Config()
    s.update_locked(dict(this=2, that=4), "sweep")
    update_arg = dict(this=8)
    s.update(update_arg)
    assert update_arg == dict(this=8)
    assert dict(s) == dict(this=2, that=4)


def test_load_config_default():
    test_path = "config-defaults.yaml"
    yaml_dict = {"epochs": {"value": 32}, "size_batch": {"value": 32}}
    with open(test_path, "w") as f:
        yaml.dump(yaml_dict, f, default_flow_style=False)
    s = wandb_sdk.Config()
    expected = sorted([("epochs", 32), ("size_batch", 32)], key=lambda x: x[0])
    actual = sorted(s.items(), key=lambda x: x[0])
    assert actual == expected
