"""
settings test.
"""

import pytest

from wandb import wandb_settings
import copy


def test_attrib_get():
    s = wandb_settings.Settings()
    assert s.base_url == "https://api.wandb.ai"


def test_attrib_set():
    s = wandb_settings.Settings()
    s.base_url = "this"
    assert s.base_url == "this"


def test_attrib_get_bad():
    s = wandb_settings.Settings()
    with pytest.raises(AttributeError):
        s.missing


def test_attrib_set_bad():
    s = wandb_settings.Settings()
    with pytest.raises(AttributeError):
        s.missing = "nope"


def test_update_dict():
    s = wandb_settings.Settings()
    s.update(dict(base_url="something2"))
    assert s.base_url == "something2"


def test_update_kwargs():
    s = wandb_settings.Settings()
    s.update(base_url="something")
    assert s.base_url == "something"

def test_copy():
    s = wandb_settings.Settings()
    s.update(base_url="changed")
    s2 = copy.copy(s)
    assert s2.base_url == "changed"
    s.update(base_url="notchanged")
    assert s.base_url == "notchanged"
    assert s2.base_url == "changed"
