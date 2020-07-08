# -*- coding: utf-8 -*-
"""
config.
"""

import logging
import os

import six
import wandb
from wandb.lib import filesystem
from wandb.lib.term import terminfo
import yaml

logger = logging.getLogger("wandb")


def _get_dict(d):
    if isinstance(d, dict):
        return d
    # assume argparse Namespace
    return vars(d)


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
        for k, v in loaded.items():
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

    def update(self, d, allow_val_change=False):
        # TODO(cling): implement allow_val_change.
        self._items.update(_get_dict(d))

    def setdefaults(self, d):
        d = _get_dict(d)
        for k, v in six.iteritems(d):
            self._items.setdefault(k, v)

    def update_locked(self, d, user=None):
        if user not in self._users:
            # TODO(jhr): use __setattr__ madness
            self._users[user] = self._users_cnt
            self._users_inv[self._users_cnt] = user
            self._users_cnt += 1

        num = self._users[user]

        for k, v in six.iteritems(d):
            self._locked[k] = num
            self._items[k] = v
