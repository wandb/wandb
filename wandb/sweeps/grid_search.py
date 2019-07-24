"""
Grid Search
"""

import itertools
import random
from wandb.sweeps.params import HyperParameter, HyperParameterSet
from wandb.sweeps.base import Search


class GridSearch(Search):
    def __init__(self, randomize_order=False):
        self.randomize_order = randomize_order

    def next_run(self, sweep):
        if 'parameters' not in sweep['config']:
            raise ValueError('Grid search requires "parameters" section')
        config = sweep['config']['parameters']
        params = HyperParameterSet.from_config(config)

        # Check that all parameters are categorical or constant
        for p in params:
            if p.type != HyperParameter.CATEGORICAL and p.type != HyperParameter.CONSTANT:
                raise ValueError(
                    'Parameter %s is a disallowed type with grid search. Grid search requires all parameters to be categorical or constant' % p.name)

        # we can only deal with discrete params in a grid search
        discrete_params = [p for p in params if p.type ==
                           HyperParameter.CATEGORICAL]

        # build an iterator over all combinations of param values
        param_names = [p.name for p in discrete_params]
        param_values = [p.values for p in discrete_params]
        param_value_set = list(itertools.product(*param_values))

        if self.randomize_order:
            random.shuffle(param_value_set)

        new_value_set = next(
            (value_set for value_set in param_value_set
             # check if parameter set is contained in some run
                if not self._runs_contains_param_values(sweep['runs'], dict(zip(param_names, value_set))
                                                        )
             ), None)

        # handle the case where we couldn't find a unique parameter set
        if new_value_set == None:
            return None

        # set next_run_params based on our new set of params
        for param, value in zip(discrete_params, new_value_set):
            param.value = value

        return (params.to_config(), None)

    def _run_contains_param_values(self, run, params):
        for key, value in params.items():
            if not key in run.config:
                return False
            if not run.config[key]['value'] == value:
                #print("not same {} {}".format(run.config[key], value))
                return False
        return True

    def _runs_contains_param_values(self, runs, params):
        ret_val = any(self._run_contains_param_values(run, params)
                      for run in runs)
        return any(self._run_contains_param_values(run, params) for run in runs)
