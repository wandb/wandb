# -*- coding: utf-8 -*-
"""
config.
"""

import inspect
import logging
import os
import types

import six
import wandb
from wandb.lib import filesystem
from wandb.lib.term import terminfo
from wandb.util import json_friendly
import yaml

try:
    # Since python 3
    from collections.abc import Sequence
except ImportError:
    # Won't work after python 3.8
    from collections import Sequence

logger = logging.getLogger("wandb")


def parse_config(params):
    if isinstance(params, dict):
        return params

    # Handle some cases where params is not a dictionary
    # by trying to convert it into a dictionary
    meta = inspect.getmodule(params)
    if meta:
        is_tf_flags_module = (
            isinstance(params, types.ModuleType)
            and meta.__name__ == "tensorflow.python.platform.flags"  # noqa: W503
        )
        if is_tf_flags_module or meta.__name__ == "absl.flags":
            params = params.FLAGS
            meta = inspect.getmodule(params)

    # newer tensorflow flags (post 1.4) uses absl.flags
    if meta and meta.__name__ == "absl.flags._flagvalues":
        params = {name: params[name].value for name in dir(params)}
    elif "__flags" in vars(params):
        # for older tensorflow flags (pre 1.4)
        if not "__parsed" not in vars(params):
            params._parse_flags()
        params = vars(params)["__flags"]
    elif not hasattr(params, "__dict__"):
        raise TypeError("config must be a dict or have a __dict__ attribute.")
    else:
        # params is a Namespace object (argparse)
        # or something else
        params = vars(params)

    # assume argparse Namespace
    return params


class ConfigError(wandb.Error):  # type: ignore
    pass


# TODO(jhr): consider a callback for persisting changes?
# if this is done right we might make sure this is pickle-able
# we might be able to do this on other objects like Run?
class Config(object):
    def __init__(self):
        object.__setattr__(self, "_items", dict())
        object.__setattr__(self, "_locked", dict())
        object.__setattr__(self, "_users", dict())
        object.__setattr__(self, "_users_inv", dict())
        object.__setattr__(self, "_users_cnt", 0)
        object.__setattr__(self, "_callback", None)

    # TODO(jhr): these class methods should go away once we merge jobspec PR
    @staticmethod
    def _save_config_file_from_dict(config_filename, run_id, config_dict):
        s = b"wandb_version: 1"
        if config_dict:  # adding an empty dictionary here causes a parse error
            s += b"\n\n" + yaml.dump(
                config_dict,
                Dumper=yaml.SafeDumper,
                default_flow_style=False,
                allow_unicode=True,
                encoding="utf-8",
            )
        data = s.decode("utf-8")
        filesystem._safe_makedirs(os.path.dirname(config_filename))
        with open(config_filename, "w") as conf_file:
            conf_file.write(data)

    @staticmethod
    def _dict_from_config_file(config_filename):
        try:
            conf_file = open(config_filename)
        except OSError:
            raise ConfigError("Couldn't read config file: %s" % config_filename)
        try:
            loaded = wandb.util.load_yaml(conf_file)
        except yaml.parser.ParserError:
            raise ConfigError("Invalid YAML in config yaml")
        config_version = loaded.pop("wandb_version", None)
        if config_version != 1:
            raise ConfigError("Unknown config version")
        data = dict()
        for k, v in six.iteritems(loaded):
            data[k] = v["value"]
        return data

    def _set_callback(self, cb):
        object.__setattr__(self, "_callback", cb)

    def __repr__(self):
        return str(dict(self))

    def keys(self):
        return [k for k in self._items.keys() if not k.startswith("_")]

    def _as_dict(self):
        return self._items

    def __getitem__(self, key):
        return self._items[key]

    def __setitem__(self, key, val):
        key, val = self._sanitize(key, val)
        if key in self._locked:
            terminfo("Config item '%s' was locked." % key)
            return
        self._items[key] = val
        logger.info("config set %s = %s - %s", key, val, self._callback)
        if self._callback:
            self._callback(key=key, val=val, data=self._as_dict())

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def _update(self, d, allow_val_change=False):
        parsed_dict = parse_config(d)
        sanitized = self._sanitize_dict(parsed_dict)
        self._items.update(sanitized)

    def update(self, d, allow_val_change=False):
        # TODO(cling): implement allow_val_change.
        self._update(d, allow_val_change)
        if self._callback:
            self._callback(data=self._as_dict())

    def persist(self):
        """Calls the callback if it's set"""
        if self._callback:
            self._callback(data=self._as_dict())

    def setdefaults(self, d):
        d = parse_config(d)
        d = self._sanitize_dict(d)
        for k, v in six.iteritems(d):
            self._items.setdefault(k, v)
        if self._callback:
            self._callback(data=self._as_dict())

    def update_locked(self, d, user=None):
        if user not in self._users:
            # TODO(jhr): use __setattr__ madness
            self._users[user] = self._users_cnt
            self._users_inv[self._users_cnt] = user
            self._users_cnt += 1

        num = self._users[user]

        for k, v in six.iteritems(d):
            k, v = self._sanitize(k, v)
            self._locked[k] = num
            self._items[k] = v

    def _sanitize_dict(self, config_dict, allow_val_change=False):
        sanitized = {}
        for k, v in six.iteritems(config_dict):
            k, v = self._sanitize(k, v)
            sanitized[k] = v

        return sanitized

    def _sanitize(self, key, val, allow_val_change=False):
        # We always normalize keys by stripping '-'
        key = key.strip("-")
        val = self._sanitize_val(val)
        if not allow_val_change:
            if key in self._items and val != self._items[key]:
                raise ConfigError(
                    (
                        'Attempted to change value of key "{}" '
                        "from {} to {}\n"
                        "If you really want to do this, pass"
                        " allow_val_change=True to config.update()"
                    ).format(key, self._items[key], val)
                )
        return key, val

    def _sanitize_val(self, val):
        """Turn all non-builtin values into something safe for YAML"""
        if isinstance(val, dict):
            converted = {}
            for key, value in six.iteritems(val):
                converted[key] = self._sanitize_val(value)
            return converted
        if isinstance(val, slice):
            converted = dict(
                slice_start=val.start, slice_step=val.step, slice_stop=val.stop
            )
            return converted
        val, _ = json_friendly(val)
        if isinstance(val, Sequence) and not isinstance(val, six.string_types):
            converted = []
            for value in val:
                converted.append(self._sanitize_val(value))
            return converted
        else:
            if val.__class__.__module__ not in ("builtins", "__builtin__"):
                val = str(val)
            return val
