"""
config tests.
"""

import pytest
import yaml
from wandb import wandb_sdk


def callback_func(key, val, data):
    print(key, val, data)


def test_attrib_get():
    s = wandb_sdk.Config()
    s._set_callback(callback_func)
    s.this = 2
    assert s.this == 2


@pytest.mark.skip(
    reason=(
        "re-enable this test when we have time to investigate "
        "locking w/ allow_val_change"
    )
)
def test_locked_set():
    s = wandb_sdk.Config()
    s.update_locked(dict(this=2, that=4), "sweep")
    s.this = 8
    assert s.this == 2


def test_load_config_default():
    test_path = "config-defaults.yaml"
    yaml_dict = {"epochs": {"value": 32}, "size_batch": {"value": 32}}
    with open(test_path, "w") as f:
        yaml.dump(yaml_dict, f, default_flow_style=False)
    s = wandb_sdk.Config()
    expected = sorted([("epochs", 32), ("size_batch", 32)], key=lambda x: x[0])
    actual = sorted(s.items(), key=lambda x: x[0])
    assert actual == expected
