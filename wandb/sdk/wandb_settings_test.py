"""
settings test.
"""

import pytest  # type: ignore

from . import wandb_settings
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


def test_update_both():
    s = wandb_settings.Settings()
    s.update(dict(base_url="somethingb"), project="nothing")
    assert s.base_url == "somethingb"
    assert s.project == "nothing"


def test_copy():
    s = wandb_settings.Settings()
    s.update(base_url="changed")
    s2 = copy.copy(s)
    assert s2.base_url == "changed"
    s.update(base_url="notchanged")
    assert s.base_url == "notchanged"
    assert s2.base_url == "changed"


def test_invalid_dict():
    s = wandb_settings.Settings()
    with pytest.raises(KeyError):
        s.update(dict(invalid="new"))


def test_invalid_kwargs():
    s = wandb_settings.Settings()
    with pytest.raises(KeyError):
        s.update(invalid="new")


def test_invalid_both():
    s = wandb_settings.Settings()
    with pytest.raises(KeyError):
        s.update(dict(project="ok"), invalid="new")
    assert s.project != "ok"
    with pytest.raises(KeyError):
        s.update(dict(wrong="bad", team="nope"), project="okbutnotset")
    assert s.team != "nope"
    assert s.project != "okbutnotset"


def test_freeze():
    s = wandb_settings.Settings()
    s.project = "goodprojo"
    assert s.project == "goodprojo"
    s.freeze()
    with pytest.raises(TypeError):
        s.project = "badprojo"
    assert s.project == "goodprojo"
    with pytest.raises(TypeError):
        s.update(project="badprojo2")
    assert s.project == "goodprojo"
    c = copy.copy(s)
    assert c.project == "goodprojo"
    c.project = "changed"
    assert c.project == "changed"


def test_bad_choice():
    s = wandb_settings.Settings()
    with pytest.raises(TypeError):
        s.mode = "goodprojo"
    with pytest.raises(TypeError):
        s.update(mode="badpro")
