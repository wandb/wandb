import numpy as np
# from wandb.sweeps import random_search
import random_search
import random
import pytest


sweep_config_2params = {'parameters': {
    'v1': {'min': 3, 'max': 5},
    'v2': {'min': 5, 'max': 6}}}

sweep_config_3params = {'parameters': {
    'v1': {'min': 3, 'max': 4},
    'v2': {'min': 5, 'max': 6}}}

sweep_config_bad = {'parameters': {
    'v1': {'max': 3, 'min': 5},
    'v2': {'min': 5, 'max': 6}}}


def test_rand_single():
    random.seed(73)
    np.random.seed(73)
    gs = random_search.RandomSearch()
    runs = []
    sweep = {'config': sweep_config_2params, 'runs': runs}
    params, info = gs.next_run(sweep)
    assert info == None
    assert params['v1']['value'] == 3 and params['v2']['value'] == 6


def test_rand_no_replacement():
    random.seed(73)
    np.random.seed(73)
    r1 = Run('b', 'finished', {
        'v1': {
            'value': 3
        },
        'v2': {
            'value': 5
        }
    }, {'zloss': 1.2}, [
        {
            'loss': 1.2
        },
    ])
    r2 = Run('b', 'finished', {
        'v1': {
            'value': 3
        },
        'v2': {
            'value': 6
        }
    }, {'loss': 0.4}, [])
    r3 = Run('b', 'finished', {
        'v1': {
             'value': 4
             },
        'v2': {
            'value': 5
        }
    }, {'loss': 0.4}, [])
    runs = [r1, r2, r3]
    sweep = {'config': sweep_config_3params, 'runs': runs}
    gs = random_search.RandomSearch()

    params, info = gs.next_run(sweep)
    print(params)
    assert info == None
    assert params['v1']['value'] == 4 and params['v2']['value'] == 6


def test_rand_bad():
    random.seed(73)
    np.random.seed(73)
    gs = random_search.RandomSearch()
    runs = []
    sweep = {'config': sweep_config_bad, 'runs': runs}
    with pytest.raises(ValueError) as excinfo:
        params, info = gs.next_run(sweep)


class Run(object):
    def __init__(self, name, state, config, summary, history):
        self.name = name
        self.state = state
        self.config = config
        self.summaryMetrics = summary
        self.history = history

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s)' % (self.name, self.state, self.config,
                                        self.history, self.summaryMetrics)


test_rand_no_replacement()
