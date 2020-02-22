"""
settings test.
"""

import pytest

from wandb import wandb_settings


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
