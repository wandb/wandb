import numpy as np
from wandb.sweeps import random_search
import random


sweep_config_2params = {'parameters': {
    'v1': {'min': 3, 'max': 5},
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
