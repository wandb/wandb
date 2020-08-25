# -*- coding: utf-8 -*-
"""
config.
"""

import logging

import six
from six.moves.collections_abc import Sequence
import wandb
from wandb.lib import config_util
from wandb.util import json_friendly

from . import wandb_helper


logger = logging.getLogger("wandb")


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
        object.__setattr__(self, "_settings", None)

    def _set_callback(self, cb):
        object.__setattr__(self, "_callback", cb)

    def _set_settings(self, settings):
        object.__setattr__(self, "_settings", settings)

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
            wandb.termwarn("Config item '%s' was locked." % key)
            return
        self._items[key] = val
        logger.info("config set %s = %s - %s", key, val, self._callback)
        if self._callback:
            self._callback(key=key, val=val, data=self._as_dict())

    def items(self):
        return [(k, v) for k, v in self._items.items() if not k.startswith("_")]

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __contains__(self, key):
        return key in self._items

    def _update(self, d, allow_val_change=None):
        parsed_dict = wandb_helper.parse_config(d)
        sanitized = self._sanitize_dict(parsed_dict)
        self._items.update(sanitized)

    def update(self, d, allow_val_change=None):
        self._update(d, allow_val_change)
        if self._callback:
            self._callback(data=self._as_dict())

    def get(self, *args):
        return self._items.get(*args)

    def persist(self):
        """Calls the callback if it's set"""
        if self._callback:
            self._callback(data=self._as_dict())

    def setdefaults(self, d):
        d = wandb_helper.parse_config(d)
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

    def _sanitize_dict(self, config_dict, allow_val_change=None):
        sanitized = {}
        for k, v in six.iteritems(config_dict):
            k, v = self._sanitize(k, v)
            sanitized[k] = v

        return sanitized

    def _sanitize(self, key, val, allow_val_change=None):
        # Let jupyter change config freely by default
        if self._settings and self._settings.jupyter and allow_val_change is None:
            allow_val_change = True
        # We always normalize keys by stripping '-'
        key = key.strip("-")
        val = self._sanitize_val(val)
        if not allow_val_change:
            if key in self._items and val != self._items[key]:
                raise config_util.ConfigError(
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
