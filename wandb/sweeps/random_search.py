"""
Random Search
"""

from wandb.sweeps.base import Search
from wandb.sweeps.params import HyperParameterSet


class RandomSearch(Search):
    def next_run(self, sweep):
        if 'parameters' not in sweep['config']:
            raise ValueError('Random search requires "parameters" section')

        sample_with_replacement = False
        if 'options' in sweep['config']:
            if sweep['config']['options']['sample_with_replacement']:
                sample_with_replacement = True

        config = sweep['config']['parameters']
        params = HyperParameterSet.from_config(config)

        if (sample_with_replacement):
            for param in params:
                param.value = param.sample()
        else:
            # build up a set of all the config values in previous runs
            # limited to the params used in this sweep
            param_names = [param.name for param in params]
            previous_runs = sweep['runs']
            previous_runs_params_list = [run.config or {}
                                         for run in previous_runs]
            previous_runs_sweep_params_list = []

            for previous_run_params in previous_runs_params_list:
                previous_run_sweep_params = []
                for param_name in param_names:
                    previous_run_sweep_params.append(
                        previous_run_params[param_name]['value'])

                previous_runs_sweep_params_list.append(
                    str(previous_run_sweep_params))

            previous_runs_sweep_params_set = set(
                previous_runs_sweep_params_list)

            # look for a set of parameters that hasn't been used in a previous run
            for i in range(10000):
                param_value_list = []
                for param in params:
                    param.value = param.sample()
                    param_value_list.append(param.value)

                if (str(param_value_list) in previous_runs_sweep_params_set):
                    continue
                else:
                    break

        return (params.to_config(), None)
