"""config tests."""

from multiprocessing.sharedctypes import Value
import pytest
import yaml
from wandb import wandb_sdk
from wandb.sdk import wandb_config


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


@pytest.fixture()
def raise_on_update_locked():
    token = wandb_config.TESTING.set(True)
    yield
    wandb_config.TESTING.reset(token)


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


def test_prevent_modification_of_locked_key(config, raise_on_update_locked):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Attempt to modify locked key 'a.b.c'
    with pytest.raises(Exception):
        config["a"]["b"]["c"] = 5

    # Ensure the value hasn't changed
    assert config["a"]["b"]["c"] == 1


def test_allow_modification_of_unlocked_key(config, raise_on_update_locked):
    config["a"] = {"b": {"c": 1, "d": 2}, "e": 3}

    # Modify unlocked key 'a.e'
    config["a"]["e"] = 10
    assert config["a"]["e"] == 10


def test_nested_config_update_with_multiple_levels(config, raise_on_update_locked):
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


def test_update_locked_with_nested_structure(config):
    user = "user1"
    nested_config = {"a": {"b": {"c": 1}, "d": 2}}
    config.update_locked(nested_config, user)

    # Check if nested keys are locked
    assert config._check_locked("a")
    assert config._check_locked("a.b")
    assert config._check_locked("a.b.c")
    assert config._check_locked("a.d")

    # Check if values are set correctly
    assert config["a"]["b"]["c"] == 1
    assert config["a"]["d"] == 2


def test_lockable_dict_prevents_modification_of_locked_key(
    config, raise_on_update_locked
):
    config["a"] = {"b": {"c": 1}}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Attempt to modify locked key 'a.b.c'
    with pytest.raises(ValueError):
        config["a"]["b"]["c"] = 2


def test_check_locked_for_ancestor_keys(config):
    config["a"] = {"b": {"c": 1}, "d": 2}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Check if ancestor key 'a' is considered locked
    assert config._check_locked("a")
    assert not config._check_locked("a.d")  # 'a.d' is not locked


def test_modification_allowed_on_unlocked_ancestor_keys(config, raise_on_update_locked):
    config["a"] = {"b": {"c": 1}, "d": 2}
    user = "user1"
    config.lock_key("a.b.c", user)

    # Modification should be allowed on 'a.d' as it's not locked
    config["a"]["d"] = 3
    assert config["a"]["d"] == 3

    # Ensure locked key 'a.b.c' remains unchanged
    assert config["a"]["b"]["c"] == 1

    # Can't update config a.b
    with pytest.raises(ValueError):
        config["a"]["b"] = 3


def test_update_with_unlocked_keys(config):
    config["a"] = 1
    config["b"] = {"c": 2}
    update_dict = {"a": 10, "b": {"c": 20}}

    config.update(update_dict, allow_val_change=True)
    assert config["a"] == 10
    assert config["b"]["c"] == 20


def test_update_with_locked_keys(config):
    config["a"] = 1
    config["b"] = {"c": 2}
    user = "user1"
    config.lock_key("a", user)
    config.lock_key("b.c", user)

    update_dict = {"a": 10, "b": {"c": 20}}
    config.update(update_dict)
    assert config["a"] == 1  # Locked key should remain unchanged
    assert config["b"]["c"] == 2  # Locked key should remain unchanged


def test_update_with_mix_of_locked_and_unlocked_keys(config):
    config["a"] = 1
    config["b"] = {"c": 2, "d": 3}
    user = "user1"
    config.lock_key("b.c", user)

    update_dict = {"a": 10, "b": {"c": 20, "d": 30}}
    config.update(update_dict, allow_val_change=True)
    assert config["a"] == 10  # Unlocked key should be updated
    assert config["b"]["c"] == 2  # Locked key should remain unchanged
    assert config["b"]["d"] == 30  # Unlocked key should be updated


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
