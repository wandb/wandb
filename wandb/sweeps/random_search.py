"""
Random Search
"""

from wandb.sweeps.base import Search
from wandb.sweeps.params import HyperParameterSet


class RandomSearch(Search):
    def next_run(self, sweep):
        # print(sweep)
        if 'parameters' not in sweep['config']:
            raise ValueError('Random search requires "parameters" section')
        config = sweep['config']['parameters']
        params = HyperParameterSet.from_config(config)

        for param in params:
            param.value = param.sample()

        return (params.to_config(), None)
