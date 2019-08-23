import numpy as np
from wandb.sweeps import grid_search
from wandb.sweeps.params import HyperParameter


class Run(object):
    def __init__(self, params):
        self.config = params


class Param(object):
    def __init__(self, name, values, type=HyperParameter.CATEGORICAL):
        self.name = name
        self.values = values
        self.type = type


sweep_config_2params = {'parameters': {
    'v1': {'values': [1, 2, 3]},
    'v2': {'values': [4, 5]}}}


def test_grid_single():
    gs = grid_search.GridSearch(randomize_order=False)
    runs = []
    sweep = {'config': sweep_config_2params, 'runs': runs}
    params, info = gs.next_run(sweep)
    assert info == None
    assert params['v1']['value'] == 1 and params['v2']['value'] == 4


def test_grid_all():
    runs = []
    num = 0
    while True:
        gs = grid_search.GridSearch()
        sweep = {'config': sweep_config_2params, 'runs': runs}
        params = gs.next_run(sweep)
        if params is None:
            break
        params, _ = params
        num += 1
        runs.append(Run(params))
        if num > 100:
            break
    assert num == 3 * 2
