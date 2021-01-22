#
# -*- coding: utf-8 -*-
"""
static settings.
"""


class SettingsStatic(object):
    def __init__(self, config):
        object.__setattr__(self, "__dict__", dict(config))

    def __setattr__(self, name, value):
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def __setitem__(self, key, val):
        raise AttributeError("Error: SettingsStatic is a readonly object")

    def keys(self):
        return self.__dict__.keys()

    def __getitem__(self, key):
        return self.__dict__[key]

    def __str__(self):
        return str(self.__dict__)
