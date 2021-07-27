# -*- coding: utf-8 -*-
"""Tune engine.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import six
import copy
from wandb.sweeps import sweepwarn, sweepdebug
from wandb.sweeps import engine


class TuneHyperOptSearch:
    def __init__(self,
                 space,
                 max_concurrent=10,
                 reward_attr=None,
                 metric="episode_reward_mean",
                 mode="max",
                 points_to_evaluate=None,
                 n_initial_points=20,
                 random_state_seed=None,
                 gamma=0.25,
                 _wandb=None,
                 **kwargs):

        from hyperopt import hp
        from ray.tune.suggest.hyperopt import HyperOptSearch
        _wandb = _wandb or {}

        space = engine.translate(space)

        # save useful parameters
        self._metric = metric
            
        # load previous results
        self._wandb_results = _wandb.get("results", [])

        if points_to_evaluate:
            sweepwarn("HyperOptSearch points_to_evaluate not supported, ignoring.")
        points_to_evaluate = []

        # FIXME(jhr): max_concurrent needs to be super high? not sure why
        # it seems that sending on_complete is still concurrent
        max_concurrent = 1000

        wandb_seed = _wandb.get("seed")
        if random_state_seed is None:
            random_state_seed = wandb_seed

        self._search = HyperOptSearch(
                space,
                max_concurrent=max_concurrent,
                reward_attr=reward_attr,
                metric=metric,
                mode=mode,
                points_to_evaluate=points_to_evaluate,
                n_initial_points=n_initial_points,
                random_state_seed=random_state_seed,
                gamma=gamma,
                **kwargs)

    def next_args(self):
        for num, run in enumerate(self._wandb_results):
            result = run["result"]
            # only handle results with a metric
            if not result:
                continue
            if self._metric not in result:
                continue

            name = "junk_%d" % num
            params = self._search._suggest(name)
            new_params = tuple((k, v) for k, v in sorted(params.items()))
            old_params = tuple((k, v) for k, v in sorted(run["params"].items()) if k in params)
            if new_params != old_params:
                # TODO(JHR): need to do a precision fuzz
                sweepdebug("mismatch {} != {}".format(new_params, old_params))
            metric_value = result.get(self._metric)
            result = {self._metric: metric_value}
            self._search.on_trial_complete(name, result)
        params = self._search._suggest("current")
        return params


class TuneRun:
    def __init__(self, spec):
        self._spec = spec
        self._results = []

        self._search = {
            "hyperopt.HyperOptSearch": TuneHyperOptSearch,
            }

    def add_result(self, result):
        # load all previous requests
        self._results.append(result.copy())

    def next_args(self):

        search_algo = self._spec.get("search_alg")
        if search_algo:
            algo = next(six.iteritems(search_algo), None)
            if algo:
                algo, cfgargs = algo
                search_class = self._search.get(algo)
                if not search_class:
                    sweepwarn("search_algo not implemented: %s" % algo)
                    return None
                # TODO() split cfgargs using cfg utility?
                args = []
                kwargs = {}
                if isinstance(cfgargs, dict):
                    if set(cfgargs.keys()) == set(("args", "kwargs")):
                        args = cfgargs.get("args")
                        kwargs = cfgargs.get("kwargs")
                    else:
                        kwargs = cfgargs
                elif isinstance(cfgargs, list):
                    args = cfgargs
                else:
                    sweepwarn("bad")

                kwargs["_wandb"] = dict(
                        results=self._results,
                        seed=self._spec.get("_wandb", {}).get("seed"))
                o = search_class(*args, **kwargs)
                p = o.next_args()
                return p
            return
        space = self._spec.get("config")
        params = engine.translate(space)
        return params

    def is_finished(self):
        num_samples = self._spec.get("num_samples")
        if num_samples and len(self._results) >= num_samples:
            return True
        return False


class Tune:
    def __init__(self):
        #super(Tune, self).__init__(_cfg_module, _cfg_version)
        pass

    def run(self, config, version=None):
        return TuneRun(config)

    def loguniform(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.loguniform(**args)

    def uniform(self, config, version=None):
        from ray import tune
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
        return tune.uniform(*args, **kwargs)

    def choice(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.choice(**args)

    def randint(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.randint(**args)

    def randn(self, config, version=None):
        from ray import tune
        args = dict(config)
        return tune.randn(**args)


tune = Tune()
