# -*- coding: utf-8 -*-
"""RayTune Search / Stopping.
"""

from wandb.sweeps.base import Search
from wandb.sweeps.params import HyperParameterSet
from wandb.sweeps import engine


def config_to_dict(config):
    params = {}
    for k, v in config.items():
        if k == "wandb_version":
            continue
        params[k] = v['value']
    return params


def dict_to_config(params):
    config_params = {}
    for k, v in params.items():
        config_params[k] = dict(value=v)
    return config_params


class RayTuneSearch(Search):
    def __init__(self):
        pass

    def next_run(self, sweep):
        sweep_id = sweep.get('name')
        runs = sweep.get('runs', [])
        results = []
        for r in runs:
            config = getattr(r, 'config', {})
            config = config_to_dict(config)
            result = getattr(r, 'summaryMetrics', {})
            results.append(dict(params=config, result=result))

        tune_config = sweep.get('config', {}).get('tune')
        tune_run = engine.execute({"tune.run": tune_config})
        if tune_run is None:
            return (None, None)

        # Add completed results
        for r in reversed(results):
            tune_run.add_result(r)

        if tune_run.is_finished():
            return (None, None)

        params = tune_run.next_args()

        config_params = dict_to_config(params)
        return (config_params, None)

    def stop_runs(self, sweep_config, runs):
        return ([], {})
