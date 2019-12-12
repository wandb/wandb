# -*- coding: utf-8 -*-
"""Tune config generation.
"""

from wandb.sweeps.config import cfg


_cfg_module = "hyperopt"
_cfg_version = "0.2.1"

class Hyperopt(cfg.SweepConfigElement):
    def __init__(self):
        super(Hyperopt, self).__init__(_cfg_module, _cfg_version)

    def uniform(self, *args, **kwargs):
        return self._config("hp.uniform", args, kwargs)

    def choice(self, *args, **kwargs):
        return self._config("hp.choice", args, kwargs)

    def loguniform(self, min_bound, max_bound, base=None):
        local_args = locals()
        return self._config("loguniform", [], local_args)


class Struct(object):
    def __init__(self, spec):
        self._spec = spec

# Define config interfaces supported
#hp = ParamObject("hyperopt")
#tune = Struct("raytune")

hp = Hyperopt()

#tune.run = ParamObject("run", extra=dict(provider=dict(name="raytune")), base=tune)
#tune.run = run
#tune.grid_search = ParamObject("grid_search")
#tune.loguniform = ParamObject("loguniform")
