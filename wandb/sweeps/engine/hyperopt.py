# -*- coding: utf-8 -*-
"""Tune engine.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import six


class HyperOpt:
    def __init__(self):
        #super(Tune, self).__init__(_cfg_module, _cfg_version)
        pass

    def loguniform(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.loguniform(**args)

    def uniform(self, config, version=None):
        from hyperopt import hp
        #print("got config", config)
        args = []
        kwargs = {}
        if isinstance(config, tuple):
            config = list(config)
        if isinstance(config, list):
            args = config
            if isinstance(args[-1], dict):
                kwargs = args.pop()
            # TODO: if final element is empty, drop it
        else:
            kwargs = config
        #print("about", args, kwargs)
        return lambda _: hp.uniform(*args, **kwargs)

    def choice(self, config, version=None):
        from hyperopt import hp
        #print("got config", config)
        args = []
        kwargs = {}
        if isinstance(config, tuple):
            config = list(config)
        if isinstance(config, list):
            args = config
            if isinstance(args[-1], dict):
                kwargs = args.pop()
            # TODO: if final element is empty, drop it
        else:
            kwargs = config
        #print("about", args, kwargs)
        #args = dict(config)
        return lambda _: hp.choice(*args, **kwargs)

    def randint(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.randint(**args)

    def randn(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.randn(**args)


hyperopt = HyperOpt()
