"""
settings test.
"""

import pytest  # type: ignore

import wandb
from wandb import Settings
import os
import copy


def test_attrib_get():
    s = Settings()
    s.setdefaults()
    assert s.base_url == "https://api.wandb.ai"


def test_attrib_set():
    s = Settings()
    s.base_url = "this"
    assert s.base_url == "this"


def test_attrib_get_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing


def test_attrib_set_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing = "nope"


def test_update_dict():
    s = Settings()
    s.update(dict(base_url="something2"))
    assert s.base_url == "something2"


def test_update_kwargs():
    s = Settings()
    s.update(base_url="something")
    assert s.base_url == "something"


def test_update_both():
    s = Settings()
    s.update(dict(base_url="somethingb"), project="nothing")
    assert s.base_url == "somethingb"
    assert s.project == "nothing"


def test_ignore_globs():
    s = Settings()
    s.setdefaults()
    assert s.ignore_globs == ()


def test_ignore_globs_explicit():
    s = Settings(ignore_globs=["foo"])
    s.setdefaults()
    assert s.ignore_globs == ("foo",)


def test_ignore_globs_env():
    s = Settings()
    s._apply_environ({"WANDB_IGNORE_GLOBS": "foo,bar"})
    s.setdefaults()
    assert s.ignore_globs == ("foo", "bar",)


@pytest.mark.skip(reason="I need to make my mock work properly with new settings")
def test_ignore_globs_settings(local_settings):
    with open(os.path.join(os.getcwd(), ".config", "wandb", "settings"), "w") as f:
        f.write(
            """[default]
ignore_globs=foo,bar"""
        )
    s = Settings(_files=True)
    s.setdefaults()
    assert s.ignore_globs == ("foo", "bar",)


def test_copy():
    s = Settings()
    s.update(base_url="changed")
    s2 = copy.copy(s)
    assert s2.base_url == "changed"
    s.update(base_url="notchanged")
    assert s.base_url == "notchanged"
    assert s2.base_url == "changed"


def test_invalid_dict():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(invalid="new"))


def test_invalid_kwargs():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(invalid="new")


def test_invalid_both():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(project="ok"), invalid="new")
    assert s.project != "ok"
    with pytest.raises(KeyError):
        s.update(dict(wrong="bad", entity="nope"), project="okbutnotset")
    assert s.entity != "nope"
    assert s.project != "okbutnotset"


def test_freeze():
    s = Settings()
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
    s = Settings()
    with pytest.raises(TypeError):
        s.mode = "goodprojo"
    with pytest.raises(TypeError):
        s.update(mode="badpro")


def test_prio_update_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.PROJECT)
    assert s.project == "pizza2"


def test_prio_update_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY)
    assert s.project == "pizza"


def test_prio_update_over_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza2"


def test_prio_update_over_both_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza2"


def test_prio_update_over_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"


def test_prio_context_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY)
    assert s.project == "pizza"
    with s._as_source(s.Source.PROJECT) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza"


def test_prio_context_over_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_over_both_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_over_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza"
    with s._as_source(s.Source.PROJECT, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza"


def test_validate_base_url():
    s = Settings()
    with pytest.raises(TypeError):
        s.update(base_url="https://wandb.ai")
    with pytest.raises(TypeError):
        s.update(base_url="https://app.wandb.ai")
    with pytest.raises(TypeError):
        s.update(base_url="http://api.wandb.ai")
    s.update(base_url="https://api.wandb.ai")
    assert s.base_url == "https://api.wandb.ai"
    s.update(base_url="https://wandb.ai.other.crazy.domain.com")
    assert s.base_url == "https://wandb.ai.other.crazy.domain.com"


def test_preprocess_base_url():
    s = Settings()
    s.update(base_url="http://host.com")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com/")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com///")
    assert s.base_url == "http://host.com"
    s.update(base_url="//http://host.com//")
    assert s.base_url == "//http://host.com"


def test_code_saving_save_code_env_false(live_mock_server, test_settings):
    test_settings.update({"save_code": None})
    os.environ["WANDB_SAVE_CODE"] = "false"
    run = wandb.init(settings=test_settings)
    assert run._settings.save_code is False


def test_code_saving_disable_code(live_mock_server, test_settings):
    test_settings.update({"save_code": None})
    os.environ["WANDB_DISABLE_CODE"] = "true"
    run = wandb.init(settings=test_settings)
    assert run._settings.save_code is False
