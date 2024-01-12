"""config tests."""

import pytest
import yaml
from wandb import wandb_sdk


def get_callback(d):
    def callback_func(key=None, val=None, data=None):
        print("CONFIG", key, val, data)
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


def test_lock_and_unlock_key(config):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}
    user = "user1"

    # Lock 'a.b.c' and check if it's locked
    config.lock_key("a.b.c", user)
    assert config._check_locked("a.b.c")

    # Unlock 'a.b.c' and check if it's unlocked
    config.unlock_key("a.b.c")
    assert not config._check_locked("a.b.c")


def test_prevent_modification_of_locked_key(config):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Attempt to modify locked key 'a.b.c'
    with pytest.raises(Exception):
        config["a"]["b"]["c"] = 5

    # Ensure the value hasn't changed
    assert config["a"]["b"]["c"] == 1


def test_allow_modification_of_unlocked_key(config):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}

    # Modify unlocked key 'a.e'
    config["a"]["e"] = 10
    assert config["a"]["e"] == 10


def test_nested_config_update_with_multiple_levels(config):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Update a nested config where one subkey is locked
    with pytest.raises(Exception):
        config["a"] = {"b": {"c": 2, "d": 3}, "e": 4, "f": {"g": 5}}

    assert config["a"]["b"]["c"] == 1  # Locked key should remain unchanged
    assert config["a"]["b"]["d"] == 3  # Unlocked key should be updated
    assert config["a"]["e"] == 4  # Unlocked key should be updated
    assert config["a"]["f"]["g"] == 5  # New nested key should be added


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
    print(err_log)
    assert warn_msg in err_log


def test_config_getattr_default(config):
    default_value = config.get("a", 1)
    assert default_value == 1

    with pytest.raises(AttributeError, match="object has no attribute 'a'"):
        _ = config.a
