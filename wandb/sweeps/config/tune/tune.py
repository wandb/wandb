# -*- coding: utf-8 -*-
"""Tune config generation.
"""

import wandb
from wandb.sweeps.config import cfg
import sys
import random


_cfg_module = "tune"
_cfg_version = "0.7.6"

tune_run_supported = dict(
            run_or_experiment=True,
            name=None,
            stop=None,
            config=None,
            resources_per_trial=None,
            num_samples=True,
            local_dir=None,
            upload_dir=None,
            trial_name_creator=None,
            loggers=None,
            sync_to_cloud=None,
            sync_to_driver=None,
            checkpoint_freq=None,
            checkpoint_at_end=None,
            keep_checkpoints_num=None,
            checkpoint_score_attr=None,
            global_checkpoint_period=None,
            export_formats=None,
            max_failures=None,
            restore=None,
            search_alg=True,
            scheduler=None,
            with_server=None,
            server_port=None,
            verbose=None,
            resume=None,
            queue_trials=None,
            reuse_actors=None,
            trial_executor=None,
            raise_on_failed_trial=None,
            return_trials=None,
            ray_auto_init=None,
            sync_function=None)


class Tune(cfg.SweepConfigElement):

    def __init__(self):
        super(Tune, self).__init__(_cfg_module, _cfg_version)

    def run(self,
            run_or_experiment,
            name=None,
            stop=None,
            config=None,
            resources_per_trial=None,
            num_samples=None,
            local_dir=None,
            upload_dir=None,
            trial_name_creator=None,
            loggers=None,
            sync_to_cloud=None,
            sync_to_driver=None,
            checkpoint_freq=None,
            checkpoint_at_end=None,
            keep_checkpoints_num=None,
            checkpoint_score_attr=None,
            global_checkpoint_period=None,
            export_formats=None,
            max_failures=None,
            restore=None,
            search_alg=None,
            scheduler=None,
            with_server=None,
            server_port=None,
            verbose=None,
            resume=None,
            queue_trials=None,
            reuse_actors=None,
            trial_executor=None,
            raise_on_failed_trial=None,
            return_trials=None,
            ray_auto_init=None,
            sync_function=None):
        local_args = locals()
        local_args.pop("self", None)
        for k, v in local_args.items():
            if not tune_run_supported.get(k) and v is not None:
                wandb.termwarn("Ignoring usupported parameter passed to tune.run(): {}".format(k))
        config = self._config("run", [], local_args, root=True)
        # Pull out program from experiment name
        config.update(dict(program=config.get("tune").get("run_or_experiment")))
        # Add auto generated random seed
        seed = random.randint(0, 2**32 - 1)
        config['tune'].setdefault('_wandb', {})
        config['tune']['_wandb'].update(dict(seed=seed))
        return config

    def uniform(self, *args, **kwargs):
        return self._config("uniform", args, kwargs)

    def loguniform(self, min_bound, max_bound, base=None):
        local_args = locals()
        return self._config("loguniform", [], local_args)


_tune = Tune()

run = _tune.run
loguniform = _tune.loguniform
uniform = _tune.uniform
