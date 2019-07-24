from wandb.sweeps import bayes_search as bayes
import numpy as np


def squiggle(x):
    return np.exp(-(x - 2) ** 2) + np.exp(-(x - 6) ** 2 / 10) + 1 / (x ** 2 + 1)


def rosenbrock(x):
    return np.sum((x[1:] - x[:-1] ** 2.0) ** 2.0 + (1 - x[:-1]) ** 2.0)


def test_squiggle():
    f = squiggle
    # we sample a ton of positive examples, ignoring the negative side
    X = np.array([np.random.uniform([0.], [5.]) for x in range(200)])
    Y = np.array([f(x) for x in X]).flatten()
    sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
        X, Y, [[-5., 5.]], improvement=1.0
    )
    assert sample[0] < 0., "Greater than 0 {}".format(sample[0])
    # we sample missing a big chunk between 1 and 3
    X = np.append(
        np.array([np.random.uniform([0.], [1.]) for x in range(200)]),
        np.array([np.random.uniform([0.], [1.]) + 4. for x in range(200)]),
        axis=0,
    )
    Y = np.array([f(x) for x in X]).flatten()
    sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
        X, Y, [[0., 4.]]
    )
    assert sample[0] > 1. and sample[0] < 4., "Sample outside of 1-3 range: {}".format(
        sample[0]
    )


def test_nans():
    f = squiggle
    X = np.array([np.random.uniform([0.], [5.]) for x in range(200)])
    Y = np.array([np.nan] * 200)
    sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
        X, Y, [[-10, 10]]
    )
    assert sample[0] < 10.  # trying all NaNs
    X += np.array([np.random.uniform([0.], [5.]) for x in range(200)])
    Y += np.array([np.nan] * 200)
    sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
        X, Y, [[-10, 10]]
    )
    assert sample[0] < 10.


def test_squiggle_int():
    f = squiggle
    X = np.array([np.random.uniform([0.], [5.]) for x in range(200)])
    Y = np.array([f(x) for x in X]).flatten()
    sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
        X, Y, [[-10, 10]]
    )
    assert sample[0] < 0., "Greater than 0 {}".format(sample[0])


def run_iterations(f, bounds, num_iterations=20):
    X = [np.zeros(len(bounds))]
    y = np.array([f(x) for x in X]).flatten()
    for jj in range(num_iterations):
        sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
            X, y, bounds, improvement=0.1
        )
        print("X: {} prob(I): {} pred: {} value: {}".format(sample, prob, pred, f(sample)))
        X = np.append(X, np.array([sample]), axis=0)
        y = np.array([f(x) for x in X]).flatten()


def run_iterations_chunked(f, bounds, num_iterations=3, chunk_size=5):
    X = [np.zeros(len(bounds))]
    y = np.array([f(x) for x in X]).flatten()
    for jj in range(num_iterations):
        sample_X = None
        for cc in range(chunk_size):
            sample, prob, pred, samples, vals, stds, sample_probs, prob_of_fail, pred_runtimes = bayes.next_sample(
                X, y, bounds, current_X=sample_X, improvement=0.1
            )
            if sample_X is None:
                sample_X = np.array([sample])
            else:
                sample_X = np.append(sample_X, np.array([sample]), axis=0)
            sample_X = np.append(X, np.array([sample]), axis=0)
        X = np.append(X, sample_X, axis=0)
        y = np.array([f(x) for x in X]).flatten()


def test_iterations_squiggle():
    run_iterations(squiggle, [[0., 5.]])


def test_iterations_rosenbrock():
    dimensions = 4
    run_iterations(rosenbrock, [[0., 5.]] * dimensions)


def test_iterations_squiggle_chunked():
    run_iterations_chunked(squiggle, [[0., 5.]])


class Run(object):
    def __init__(self, name, state, config, summary, history):
        self.name = name
        self.state = state
        self.config = config
        self.summaryMetrics = summary
        self.history = history

    def __repr__(self):
        return 'Run(%s,%s,%s,%s,%s)' % (self.name, self.state, self.config, self.history, self.summaryMetrics)


sweep_config_2params = {
    'metric': {
        'name': 'loss'
        },
    'parameters': {
        'v1': {'min': 1, 'max': 10},
        'v2': {'min': 1, 'max': 10}}}


# search with 0 runs - hardcoded results
def test_runs_bayes():
    np.random.seed(73)
    bs = bayes.BayesianSearch()
    runs = []
    sweep = {'config': sweep_config_2params, 'runs': runs}
    params, info = bs.next_run(sweep)
    assert params['v1']['value'] == 7 and params['v2']['value'] == 6


# search with 2 finished runs - hardcoded results
def test_runs_bayes_runs2():
    np.random.seed(73)
    bs = bayes.BayesianSearch()
    r1 = Run('b', 'finished',
             {'v1': {'value': 7},
              'v2': {'value': 6}},
             {'zloss': 1.2},
             [{'loss': 1.2},
              ]
             )
    r2 = Run('b', 'finished',
             {'v1': {'value': 1},
              'v2': {'value': 8}},
             {'loss': 0.4},
             []
             )
    # need two (non running) runs before we get a new set of parameters
    runs = [r1, r2]
    sweep = {'config': sweep_config_2params, 'runs': runs}
    params, info = bs.next_run(sweep)
    assert params['v1']['value'] == 2 and params['v2']['value'] == 9


# search with 2 finished runs - hardcoded results - missing metric
def test_runs_bayes_runs2_missingmetric():
    np.random.seed(73)
    bs = bayes.BayesianSearch()
    r1 = Run('b', 'finished',
             {'v1': {'value': 7},
              'v2': {'value': 5}},
             {'xloss': 0.2},
             []
             )
    runs = [r1, r1]
    sweep = {'config': sweep_config_2params, 'runs': runs}
    params, info = bs.next_run(sweep)
    assert params['v1']['value'] == 1 and params['v2']['value'] == 1
