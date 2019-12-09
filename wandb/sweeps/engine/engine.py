# -*- coding: utf-8 -*-
"""Interpret SweepConfig object.
"""

from wandb.sweeps.config import SweepConfig
from wandb.sweeps import config
from wandb.sweeps import engine
from wandb.sweeps import util
from wandb.sweeps import sweeperror


supported = {
        "tune": engine.tune,
        "hyperopt.hp": engine.hyperopt,
        }


def execute(config):
    if not isinstance(config, dict):
        sweeperror("Expecting dict: %s" % config)
        return

    top_level_keys = list(config.keys())
    if len(top_level_keys) != 1:
        sweeperror("Expecting only 1 toplevel config key (Found %d)" % len(top_level_keys))
        return
    top_level = top_level_keys[0]
    top_value = config.get(top_level)
    top_mod, top_func = util.pad(top_level.rsplit('.', 1), 2, left=True)
    if not top_mod:
        sweeperror("Required module specification: mod.func")
        return

    eng_obj = supported.get(top_mod)
    if not eng_obj:
        sweeperror("Module not supported: %s" % top_mod)
        return

    if top_func.startswith("_"):
        sweeperror("function specified is internal: %s" % top_func)
        return

    func = getattr(eng_obj, top_func, None)
    if not func:
        sweeperror("function not found: %s" % top_func)
        return

    return func(top_value)


def translate(space):
    params = {}
    for k, v in space.items():
        if isinstance(v, dict):
            op = execute(v)
            # FIXME(jhr): make this part of specific engine, not in generic engine?
            if getattr(op, 'func', None):
                v = op.func(1)
            else:
                v = op(1)
        params[k] = v
    return params
