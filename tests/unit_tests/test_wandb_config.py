"""config tests."""

import pytest
import yaml
from wandb import sdk as wandb_sdk
from wandb.sdk.lib import config_util


def get_callback(d):
    def callback_func(key=None, val=None, data=None):
        if data:
            d.update(data)
        if key:
            d[key] = val

    return callback_func


@pytest.fixture()
def consolidated():
    return {}


@pytest.fixture()
def callback(consolidated):
    return get_callback(consolidated)


@pytest.fixture()
def config(callback):
    s = wandb_sdk.Config()
    s._set_callback(callback)
    return s


def test_attrib_set(consolidated, config):
    config.this = 2
    assert dict(config) == dict(this=2)
    assert consolidated == dict(config)


def test_locked_set_attr(consolidated, config):
    config.update_locked(dict(this=2, that=4), "sweep")
    config.this = 8
    assert config.this == 2
    assert config.that == 4
    assert dict(config) == dict(this=2, that=4)
    assert consolidated == dict(config)


def test_locked_set_key(consolidated, config):
    config.update_locked(dict(this=2, that=4), "sweep")
    config["this"] = 8
    assert config["this"] == 2
    assert config["that"] == 4
    assert dict(config) == dict(this=2, that=4)
    assert consolidated == dict(config)


def test_update(consolidated, config):
    config.update(dict(this=8))
    assert dict(config) == dict(this=8)
    config.update(dict(that=4))
    assert dict(config) == dict(this=8, that=4)
    assert consolidated == dict(config)


def test_setdefaults(consolidated, config):
    config.update(dict(this=8))
    assert dict(config) == dict(this=8)
    config.setdefaults(dict(extra=2, another=4))
    assert dict(config) == dict(this=8, extra=2, another=4)
    assert consolidated == dict(config)


def test_setdefaults_existing(consolidated, config):
    config.update(dict(this=8))
    assert dict(config) == dict(this=8)
    config.setdefaults(dict(extra=2, this=4))
    assert dict(config) == dict(this=8, extra=2)
    assert consolidated == dict(config)


def test_locked_update(consolidated, config):
    config.update_locked(dict(this=2, that=4), "sweep")
    config.update(dict(this=8))
    assert dict(config) == dict(this=2, that=4)
    assert consolidated == dict(config)


def test_locked_no_sideeffect(consolidated, config):
    config.update_locked(dict(this=2, that=4), "sweep")
    update_arg = dict(this=8)
    config.update(update_arg)
    assert update_arg == dict(this=8)
    assert dict(config) == dict(this=2, that=4)
    assert consolidated == dict(config)


def test_load_config_default():
    test_path = "config-defaults.yaml"
    yaml_dict = {"epochs": {"value": 32}, "size_batch": {"value": 32}}
    with open(test_path, "w") as f:
        yaml.dump(yaml_dict, f, default_flow_style=False)
    config = wandb_sdk.Config()
    assert dict(config) == dict(epochs=32, size_batch=32)


def test_load_empty_config_default(capsys):
    test_path = "config-defaults.yaml"
    with open(test_path, "w"):
        pass
    _ = wandb_sdk.Config()
    err_log = capsys.readouterr().err
    warn_msg = "wandb: WARNING Found an empty default config file (config-defaults.yaml). Proceeding with no defaults."
    assert warn_msg in err_log


@pytest.mark.parametrize(
    "contents",
    [
        "a: [1, 2\n",
        "a: b: c\n",
        'a: "unclosed\n',
        "a:\n\t- 1\n",
    ],
    ids=["parser", "mapping", "quote", "tab"],
)
def test_load_invalid_yaml_config_default(monkeypatch, tmp_path, contents):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config-defaults.yaml").write_text(contents)

    with pytest.raises(config_util.ConfigError, match="Invalid YAML"):
        wandb_sdk.Config()


def test_config_getattr_default(config):
    default_value = config.get("a", 1)
    assert default_value == 1

    with pytest.raises(AttributeError, match="object has no attribute 'a'"):
        _ = config.a


def test_nested_config_overwrite(consolidated, config):
    config.update({"path": {"to": {"override": "baz", "keep": "baf"}}})
    config.merge_locked(
        {"path": {"to": {"override": "bar"}}}, "sweep", _allow_val_change=True
    )
    assert dict(config) == {"path": {"to": {"override": "bar", "keep": "baf"}}}
    assert consolidated == dict(config)
