"""config."""

import logging

import wandb
from wandb.util import (
    _is_artifact_representation,
    check_dict_contains_nested_artifact,
    json_friendly_val,
)

from . import wandb_helper
from .lib import config_util

from typing import Optional

logger = logging.getLogger("wandb")


# TODO(jhr): consider a callback for persisting changes?
# if this is done right we might make sure this is pickle-able
# we might be able to do this on other objects like Run?
class Config:
    """Config object.

    Config objects are intended to hold all of the hyperparameters associated with
    a wandb run and are saved with the run object when `wandb.init` is called.

    We recommend setting `wandb.config` once at the top of your training experiment or
    setting the config as a parameter to init, ie. `wandb.init(config=my_config_dict)`

    You can create a file called `config-defaults.yaml`, and it will automatically be
    loaded into `wandb.config`. See https://docs.wandb.com/guides/track/config#file-based-configs.

    You can also load a config YAML file with your custom name and pass the filename
    into `wandb.init(config="special_config.yaml")`.
    See https://docs.wandb.com/guides/track/config#file-based-configs.

    Examples:
        Basic usage
        ```
        wandb.config.epochs = 4
        wandb.init()
        for x in range(wandb.config.epochs):
            # train
        ```

        Using wandb.init to set config
        ```
        wandb.init(config={"epochs": 4, "batch_size": 32})
        for x in range(wandb.config.epochs):
            # train
        ```

        Nested configs
        ```
        wandb.config['train']['epochs'] = 4
        wandb.init()
        for x in range(wandb.config['train']['epochs']):
            # train
        ```

        Using absl flags
        ```
        flags.DEFINE_string(‘model’, None, ‘model to run’) # name, default, help
        wandb.config.update(flags.FLAGS) # adds all absl flags to config
        ```

        Argparse flags
        ```python
        wandb.init()
        wandb.config.epochs = 4

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-b",
            "--batch-size",
            type=int,
            default=8,
            metavar="N",
            help="input batch size for training (default: 8)",
        )
        args = parser.parse_args()
        wandb.config.update(args)
        ```

        Using TensorFlow flags (deprecated in tensorflow v2)
        ```python
        flags = tf.app.flags
        flags.DEFINE_string("data_dir", "/tmp/data")
        flags.DEFINE_integer("batch_size", 128, "Batch size.")
        wandb.config.update(flags.FLAGS)  # adds all of the tensorflow flags to config
        ```
    """

    def __init__(self):
        object.__setattr__(self, "_items", dict())
        object.__setattr__(self, "_locked_items", dict())
        object.__setattr__(self, "_users", dict())
        object.__setattr__(self, "_users_inv", dict())
        object.__setattr__(self, "_users_cnt", 0)
        object.__setattr__(self, "_callback", None)
        object.__setattr__(self, "_settings", None)
        object.__setattr__(self, "_artifact_callback", None)

        self._load_defaults()

    def _set_callback(self, cb):
        object.__setattr__(self, "_callback", cb)

    def _set_artifact_callback(self, cb):
        object.__setattr__(self, "_artifact_callback", cb)

    def _set_settings(self, settings):
        object.__setattr__(self, "_settings", settings)

    def __repr__(self):
        return str(dict(self))

    def keys(self):
        return [k for k in self._read_interface.keys() if not k.startswith("_")]

    @property
    def _read_interface(self) -> dict:
        return config_util.merge_dicts(self._items, self._locked_items)

    def _as_dict(self):
        return self._read_interface

    def as_dict(self):
        # TODO: add telemetry, deprecate, then remove
        return dict(self)

    def __getitem__(self, key):
        return self._read_interface[key]

    def __setitem__(self, key, val):
        with wandb.sdk.lib.telemetry.context() as tel:
            tel.feature.set_config_item = True
        self._raise_value_error_on_nested_artifact(val, nested=True)
        key, val = self._sanitize(key, val)
        self._items[key] = val
        logger.info("config set %s = %s - %s", key, val, self._callback)
        if self._callback:
            self._callback(key=key, val=val)

    def items(self):
        return [
            (k, v) for k, v in self._read_interface.items() if not k.startswith("_")
        ]

    __setattr__ = __setitem__

    def __getattr__(self, key):
        try:
            return self.__getitem__(key)
        except KeyError as ke:
            raise AttributeError(
                f"{self.__class__!r} object has no attribute {key!r}"
            ) from ke

    def __contains__(self, key):
        return key in self._read_interface

    def _update(self, d, allow_val_change=None, ignore_locked=None):
        # TODO: handle ignore_locked
        # TODO: make sure sanitized is right
        parsed_dict = wandb_helper.parse_config(d)

        dict_differences = config_util.dict_differ(self._locked_items, parsed_dict)
        modified_key_tree = config_util.construct_dict_from_paths(
            dict_differences["modified"]
        )

        # TODO: implement
        # self._warn_for_modify(modified_key_tree)

        # remove items from sanitized that are already locked
        added = config_util.construct_dict_from_paths_and_values(
            dict_differences["added"], parsed_dict
        )

        sanitized = self._sanitize_dict(added)

        self.check_update(sanitized, allow_val_change)
        self._items.update(sanitized)

        return sanitized

    def update(self, d, allow_val_change=None):
        sanitized = self._update(d, allow_val_change)

        if self._callback:
            # TODO: use dict(self) here
            self._callback(data=sanitized)

    def get(self, *args):
        return self._read_interface.get(*args)

    def persist(self):
        """Call the callback if it's set."""
        if self._callback:
            self._callback(data=self._as_dict())

    def setdefaults(self, d):
        d = wandb_helper.parse_config(d)
        # strip out keys already configured
        d = {k: v for k, v in d.items() if k not in self._items}
        d = self._sanitize_dict(d)
        self._items.update(d)
        if self._callback:
            self._callback(data=d)

    def check_update(self, d, _allow_val_change=None):
        if not _allow_val_change:
            read_interface = self._read_interface
            changes = config_util.dict_differ(read_interface, d)
            modified_existing_key = len(changes["modified"]) > 0
            if modified_existing_key:
                path = changes["modified"][0]
                for subkey in path:
                    original_val = read_interface[subkey]
                    val = d[subkey]
                key = ".".join(path)

                raise config_util.ConfigError(
                    f'Attempted to change value of key "{key}" '
                    f"from {original_val} to {val}\n"
                    "If you really want to do this, pass"
                    " allow_val_change=True to config.update()"
                )

    def update_locked(self, d, user=None, _allow_val_change=None):
        """
        if user not in self._users:
            self._users[user] = self._users_cnt
            self._users_inv[self._users_cnt] = user
            object.__setattr__(self, "_users_cnt", self._users_cnt + 1)

        num = self._users[user]

        for k, v in d.items():
            k, v = self._sanitize(k, v, allow_val_change=_allow_val_change)
            self._locked[k] = num
            self._items[k] = v
        """

        sanitized = self._sanitize_dict(d)

        self.check_update(sanitized, _allow_val_change)

        object.__setattr__(
            self,
            "_locked_items",
            config_util.merge_dicts(self._locked_items, sanitized),
        )

        if self._callback:
            self._callback(data=sanitized)

    def _load_defaults(self):
        conf_dict = config_util.dict_from_config_file("config-defaults.yaml")
        if conf_dict is not None:
            self.update(conf_dict)

    def _sanitize_dict(
        self,
        config_dict,
        # allow_val_change=None,
        ignore_keys: Optional[set] = None,
    ):
        sanitized = {}
        self._raise_value_error_on_nested_artifact(config_dict)
        for k, v in config_dict.items():
            """
            if ignore_keys and k in ignore_keys:
                continue
            """
            k, v = self._sanitize(k, v)
            sanitized[k] = v
        return sanitized

    def _sanitize(self, key, val):
        # TODO: enable WBValues in the config in the future
        # refuse all WBValues which is all Media and Histograms
        if isinstance(val, wandb.sdk.data_types.base_types.wb_value.WBValue):
            raise ValueError("WBValue objects cannot be added to the run config")
        # Let jupyter change config freely by default
        if self._settings and self._settings._jupyter and allow_val_change is None:
            allow_val_change = True
        # We always normalize keys by stripping '-'
        key = key.strip("-")
        if _is_artifact_representation(val):
            val = self._artifact_callback(key, val)
        # if the user inserts an artifact into the config
        if not isinstance(val, wandb.Artifact):
            val = json_friendly_val(val)
        if isinstance(val, dict):
            val = self._sanitize_dict(val)
        """
        if not allow_val_change:
            read_interface = self._read_interface
            if key in read_interface and val != read_interface[key]:
                raise config_util.ConfigError(
                    f'Attempted to change value of key "{key}" '
                    f"from {read_interface[key]} to {val}\n"
                    "If you really want to do this, pass"
                    " allow_val_change=True to config.update()"
                )
        """
        return key, val

    def _raise_value_error_on_nested_artifact(self, v, nested=False):
        # we can't swap nested artifacts because their root key can be locked by other values
        # best if we don't allow nested artifacts until we can lock nested keys in the config
        if isinstance(v, dict) and check_dict_contains_nested_artifact(v, nested):
            raise ValueError(
                "Instances of wandb.Artifact can only be top level keys in wandb.config"
            )


class ConfigStatic:
    def __init__(self, config):
        object.__setattr__(self, "__dict__", dict(config))

    def __setattr__(self, name, value):
        raise AttributeError("Error: wandb.run.config_static is a readonly object")

    def __setitem__(self, key, val):
        raise AttributeError("Error: wandb.run.config_static is a readonly object")

    def keys(self):
        return self.__dict__.keys()

    def __getitem__(self, key):
        return self.__dict__[key]

    def __str__(self):
        return str(self.__dict__)
