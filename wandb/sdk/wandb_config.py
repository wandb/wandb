# -*- coding: utf-8 -*-
"""
config.
"""

import logging

import six

from wandb.util.term import terminfo

logger = logging.getLogger("wandb")


def _get_dict(d):
    if isinstance(d, dict):
        return d
    # assume argparse Namespace
    return vars(d)


# TODO(jhr): consider a callback for persisting changes?
# if this is done right we might make sure this is pickle-able
# we might be able to do this on other objects like Run?
class Config(object):
    def __init__(self):
        object.__setattr__(self, '_items', dict())
        object.__setattr__(self, '_locked', dict())
        object.__setattr__(self, '_users', dict())
        object.__setattr__(self, '_users_inv', dict())
        object.__setattr__(self, '_users_cnt', 0)
        object.__setattr__(self, '_callback', None)

    def _set_callback(self, cb):
        object.__setattr__(self, '_callback', cb)

    def __repr__(self):
        return str(dict(self))

    def keys(self):
        return [k for k in self._items.keys() if not k.startswith('_')]

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

    def update(self, d):
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
