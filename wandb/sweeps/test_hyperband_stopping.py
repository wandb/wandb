from wandb.sweeps import hyperband_stopping as search
import numpy as np


def test_hyperband_min_iter_bands():
    hbet = search.HyperbandEarlyTerminate.init_from_min_iter(3, 3)
    assert (hbet.bands[:3] == [3, 9, 27])


def test_hyperband_max_iter_bands():
    hbet = search.HyperbandEarlyTerminate.init_from_max_iter(81, 3, 3)
    assert (hbet.bands[:3] == [3, 9, 27])


class Run(object):
    def __init__(self, name, state, history):
        self.name = name
        self.state = state
        self.history = history


def test_init_from_max_iter():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(18, 3, 2)
    assert et.bands == [2, 6]


def test_single_run():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(18, 3, 2)
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'running',
             [{'loss': 10},
              {'loss': 9},
              {'loss': 8},
              {'loss': 7},
              {'loss': 6},
              {'loss': 5},
              {'loss': 4},
              {'loss': 3},
              {'loss': 2},
              {'loss': 1},
              ])]
    )
    assert stopped == []


def test_2runs_band1_stop():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(18, 3, 2)
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'running',
             [{'loss': 10},
              {'loss': 9},
              {'loss': 8},
              {'loss': 7},
              {'loss': 6},
              {'loss': 5},
              {'loss': 4},
              {'loss': 3},
              {'loss': 2},
              {'loss': 1},
              ]),
         Run('b', 'running',
             [{'loss': 10},
              {'loss': 10},
              {'loss': 10},
              ]),
         ]
    )
    assert stopped == ['b']


def test_2runs_band1_pass():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(18, 3, 2)
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'running',
             [{'loss': 10},
              {'loss': 9},
              {'loss': 8},
              {'loss': 7},
              {'loss': 6},
              {'loss': 5},
              {'loss': 4},
              {'loss': 3},
              {'loss': 2},
              {'loss': 1},
              ]),
         Run('b', 'running',
             [{'loss': 10},
              {'loss': 10},
              {'loss': 6},
              ]),
         ]
    )
    assert stopped == []


def test_skipped_steps():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(18, 3, 2)
    et._load_metric_name_and_goal({'metric': {
        'name': 'loss',
        'goal': 'minimize'
    }})
    line = et._load_run_metric_history(
        Run('a', 'running',
            [{'loss': 10},
             {'a': 9},
             {'a': 8},
             {'a': 7},
             {'loss': 6},
             {'a': 5},
             {'a': 4},
             {'a': 3},
             {'a': 2},
             {'loss': 1},
             ]))
    assert line == [10, 6, 1]

def test_2runs_band1_stop_2():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(5, 3, 2)
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'stopped',
             [{'loss': 10},
              {'loss': 9},
              {'loss': 8},
              {'loss': 7},
              {'loss': 6},
              {'loss': 5},
              {'loss': 4},
              {'loss': 3},
              {'loss': 2},
              {'loss': 1},
              ]),
         Run('b', 'running',
             [{'loss': 10},
              {'loss': 10},
              {'loss': 10},
              ]),
         ]
    )
    assert stopped == ['b']

def test_5runs_band1_stop_2():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(5, 2, 2)
    # bands are at 1 and 2
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'stopped',  # This wont be stopped because already stopped
             [{'loss': 10},
              {'loss': 9},
              ]),
        Run('b', 'running',   # This should be stopped
             [{'loss': 10},
              {'loss': 10},
              ]),
        Run('c', 'running',   # This passes band 1 but not band 2
             [{'loss': 10},
              {'loss': 8},
              {'loss': 8},
              ]),
        Run('d', 'running',
             [{'loss': 10},
              {'loss': 7},
              {'loss': 7},
              ]),
        Run('e', 'finished',
             [{'loss': 10},
              {'loss': 6},
              {'loss': 6},
              ]),
         ]
    )
    assert stopped == ['b', 'c']

def test_5runs_band1_stop_2_1stnoband():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(5, 2, 2)
    # bands are at 1 and 2
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'running',  # This wont be stopped because not at band 1
             [{'loss': 10},
              ]),
        Run('b', 'running',   # This should be stopped
             [{'loss': 10},
              {'loss': 10},
              ]),
        Run('c', 'running',   # This passes band 1 but not band 2
             [{'loss': 10},
              {'loss': 8},
              {'loss': 8},
              ]),
        Run('d', 'running',
             [{'loss': 10},
              {'loss': 7},
              {'loss': 7},
              ]),
        Run('e', 'finished',
             [{'loss': 10},
              {'loss': 6},
              {'loss': 6},
              ]),
         ]
    )
    assert stopped == ['b', 'c']

def test_eta_3():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(9, 3, 2)
    # bands are at 1 and 3, thresholds are 7 and 4
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'minimize',
    }},
        [Run('a', 'stopped',  # This wont be stopped because already stopped
             [{'loss': 10},
              {'loss': 9},
              ]),
        Run('b', 'running',   # This should be stopped
             [{'loss': 10},
              {'loss': 10},
              ]),
        Run('c', 'running',   # This fails the first threeshold but snuck in so we wont kill
             [{'loss': 10},
              {'loss': 8},
              {'loss': 8},
              {'loss': 3},
              ]),
        Run('d', 'running',
             [{'loss': 10},
              {'loss': 7},
              {'loss': 7},
              {'loss': 4},
              ]),
        Run('e', 'running', # this passes band 1 but doesn't pass band 2
             [{'loss': 10},
              {'loss': 6},
              {'loss': 6},
              {'loss': 6},
              ]),
         ]
    )
    assert stopped == ['b', 'e']

def test_eta_3_max():
    et = search.HyperbandEarlyTerminate.init_from_max_iter(9, 3, 2)
    # bands are at 1 and 3, thresholds are 7 and 4
    stopped, lines = et.stop_runs({'metric': {
        'name': 'loss',
        'goal': 'maximize',
    }},
        [Run('a', 'stopped',  # This wont be stopped because already stopped
             [{'loss': -10},
              {'loss': -9},
              ]),
        Run('b', 'running',   # This should be stopped
             [{'loss': -10},
              {'loss': -10},
              ]),
        Run('c', 'running',   # This fails the first threeshold but snuck in so we wont kill
             [{'loss': -10},
              {'loss': -8},
              {'loss': -8},
              {'loss': -3},
              ]),
        Run('d', 'running',
             [{'loss': -10},
              {'loss': -7},
              {'loss': -7},
              {'loss': -4},
              ]),
        Run('e', 'running', # this passes band 1 but doesn't pass band 2
             [{'loss': -10},
              {'loss': -6},
              {'loss': -6},
              {'loss': -6},
              ]),
         ]
    )
    assert stopped == ['b', 'e']


