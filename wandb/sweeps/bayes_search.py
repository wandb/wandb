"""
Bayesian Search

Check out https://arxiv.org/pdf/1206.2944.pdf
 for explanation of bayesian optimization

We do bayesian optimization and handle the cases where some X values are integers
as well as the case where X is very large.

"""

import numpy as np
#from sklearn.gaussian_process import GaussianProcessRegressor
#from sklearn.gaussian_process.kernels import Matern
#import scipy.stats as stats
import math
from wandb.util import get_module
from wandb.sweeps.base import Search
from wandb.sweeps.params import HyperParameter, HyperParameterSet

sklearn_gaussian = get_module('sklearn.gaussian_process')
scipy_stats = get_module('scipy.stats')


def fit_normalized_gaussian_process(X, y, nu=1.5):
    """
        We fit a gaussian process but first subtract the mean and divide by stddev.
        To undo at prediction tim, call y_pred = gp.predict(X) * y_stddev + y_mean
    """
    gp = sklearn_gaussian.GaussianProcessRegressor(
        kernel=sklearn_gaussian.kernels.Matern(nu=nu), n_restarts_optimizer=2, alpha=0.0000001, random_state=2
    )
    if len(y) == 1:
        y = np.array(y)
        y_mean = y[0]
        y_stddev = 1
    else:
        y_mean = np.mean(y)
        y_stddev = np.std(y) + 0.0001
    y_norm = (y - y_mean) / y_stddev
    gp.fit(X, y_norm)
    return gp, y_mean, y_stddev


def sigmoid(x):
    return np.exp(-np.logaddexp(0, -x))


def random_sample(X_bounds, num_test_samples):
    num_hyperparameters = len(X_bounds)
    test_X = np.empty((num_test_samples, num_hyperparameters))
    for ii in range(num_test_samples):
        for jj in range(num_hyperparameters):
            if type(X_bounds[jj][0]) == int:
                assert (type(X_bounds[jj][1]) == int)
                test_X[ii, jj] = np.random.randint(
                    X_bounds[jj][0], X_bounds[jj][1])
            else:
                test_X[ii, jj] = np.random.uniform() * (
                    X_bounds[jj][1] - X_bounds[jj][0]
                ) + X_bounds[
                    jj
                ][
                    0
                ]
    return test_X


def predict(X, y, test_X, nu=1.5):
    gp, norm_mean, norm_stddev = fit_normalized_gaussian_process(X, y, nu=nu)
    y_pred, y_std = gp.predict([test_X], return_std=True)
    y_std_norm = y_std * norm_stddev
    y_pred_norm = (y_pred * norm_stddev) + norm_mean
    return y_pred_norm[0], y_std_norm[0]


def train_runtime_model(sample_X, runtimes, X_bounds):
    if sample_X.shape[0] != runtimes.shape[0]:
        raise ValueError("Sample X and runtimes must be the same length")

    return train_gaussian_process(sample_X, runtimes, X_bounds)


#def train_failure_model(sample_X, failures, X_bounds):
#    if sample_X.shape[0] != failures.shape[0]:
#        raise ValueError("Sample X and runtimes must be the same length")
#
#    return train_gaussian_process(sample_X, runtimes, X_bounds)


def train_gaussian_process(
    sample_X, sample_y, X_bounds, current_X=None, nu=1.5, max_samples=100
):
    """
    Trains a Gaussian Process function from sample_X, sample_y data

    Handles the case where there are other training runs in flight (current_X)

        Arguments:
            sample_X - vector of already evaluated sets of hyperparameters
            sample_y - vector of already evaluated loss function values
            X_bounds - minimum and maximum values for every dimension of X
            current_X - hyperparameters currently being explored
            nu - input to the Matern function, higher numbers make it smoother 0.5, 1.5, 2.5 are good values
             see http://scikit-learn.org/stable/modules/generated/sklearn.gaussian_process.kernels.Matern.html

        Returns:
            gp - the gaussian process function
            y_mean - mean 
            y_stddev - stddev

            To make a prediction with gp on real world data X, need to call:
            (gp.predict(X) * y_stddev) + y_mean

    """
    if current_X is not None:
        current_X = np.array(current_X)
        if len(current_X.shape) != 2:
            raise ValueError("Current X must be a 2 dimensional array")

        # we can't let the current samples be bigger than max samples
        # because we need to use some real samples to build the curve
        if current_X.shape[0] > max_samples - 5:
            print(
                "current_X is bigger than max samples - 5 so dropping some currently running parameters"
            )
            current_X = current_X[:(max_samples - 5), :]
    if len(sample_y.shape) != 1:
        raise ValueError("Sample y must be a 1 dimensional array")

    if sample_X.shape[0] != sample_y.shape[0]:
        raise ValueError(
            "Sample X and sample y must be the same size {} {}".format(
                sample_X.shape[0], sample_y.shape[0]
            )
        )

    if X_bounds is not None and sample_X.shape[1] != len(X_bounds):
        raise ValueError(
            "Bounds must be the same length as Sample X's second dimension"
        )

    # gaussian process takes a long time to train, so if there's more than max_samples
    # we need to sample from it
    if sample_X.shape[0] > max_samples:
        sample_indices = np.random.randint(sample_X.shape[0], size=max_samples)
        X = sample_X[sample_indices]
        y = sample_y[sample_indices]
    else:
        X = sample_X
        y = sample_y
    gp, y_mean, y_stddev = fit_normalized_gaussian_process(X, y, nu=nu)
    if current_X is not None:
        # if we have some hyperparameters running, we pretend that they return
        # the prediction of the function we've fit
        X = np.append(X, current_X, axis=0)
        current_y_fantasy = (gp.predict(current_X) * y_stddev) + y_mean
        y = np.append(y, current_y_fantasy)
        gp, y_mean, y_stddev = fit_normalized_gaussian_process(X, y, nu=nu)
    return gp, y_mean, y_stddev


def filter_weird_values(sample_X, sample_y):
    is_row_finite = ~(np.isnan(sample_X).any(axis=1) | np.isnan(sample_y))
    sample_X = sample_X[is_row_finite, :]
    sample_y = sample_y[is_row_finite]
    return sample_X, sample_y


def next_sample(
    sample_X,
    sample_y,
    X_bounds=None,
    runtimes=None,
    failures=None,
    current_X=None,
    nu=1.5,
    max_samples_for_gp=100,
    improvement=0.01,
    num_points_to_try=1000,
    opt_func="expected_improvement",
    test_X=None,
):
    """
        Calculates the best next sample to look at via bayesian optimization.

        Check out https://arxiv.org/pdf/1206.2944.pdf
         for explanation of bayesian optimization

        Arguments:
            sample_X - 2d array of already evaluated sets of hyperparameters
            sample_y - 1d array of already evaluated loss function values
            X_bounds - 2d array minimum and maximum values for every dimension of X

            runtimes - vector of length sample_y - should be the time taken to train each model in sample X
            failures - vector of length sample_y - should be True for models where training failed and False where
                training succeeded.  This model will throw out NaNs and Infs so if you want it to avaoid 
                failure values for X, use this failure vector.

            current_X - hyperparameters currently being explored
            nu - input to the Matern function, higher numbers make it smoother 0.5, 1.5, 2.5 are good values
             see http://scikit-learn.org/stable/modules/generated/sklearn.gaussian_process.kernels.Matern.html

            max_samples_for_gp - maximum samples to consider (since algo is O(n^3)) for performance, but also adds some randomness
            improvement - amount of improvement to optimize for -- higher means take more exploratory risks
            num_points_to_try - number of X values to try when looking for value with highest
                        expected probability of improvement
            opt_func - one of {"expected_improvement", "prob_of_improvement"} - whether to optimize expected
                improvement of probability of improvement.  Expected improvement is generally better - may want
                to remove probability of improvement at some point.  (But I think prboability of improvement
                is a little easier to calculate)
            test_X - X values to test when looking for the best values to try

        Returns:
            suggested_X - X vector to try running next
            suggested_X_prob_of_improvement - probability of the X vector beating the current best
            suggested_X_predicted_y - predicted output of the X vector
            test_X - 2d array of length num_points_to_try by num features: tested X values
            y_pred - 1d array of length num_points_to_try: predicted values for test_X
            y_pred_std - 1d array of length num_points_to_try: predicted std deviation for test_X
            prob_of_improve 1d array of lenth num_points_to_try: predicted porbability of improvement
            prob_of_failure 1d array of predicted probabilites of failure
            expected_runtime 1d array of expected runtimes
    """
    # Sanity check the data
    sample_X = np.array(sample_X)
    sample_y = np.array(sample_y)
    if test_X is not None:
        test_X = np.array(test_X)
    if len(sample_X.shape) != 2:
        raise ValueError("Sample X must be a 2 dimensional array")

    if len(sample_y.shape) != 1:
        raise ValueError("Sample y must be a 1 dimensional array")

    if sample_X.shape[0] != sample_y.shape[0]:
        raise ValueError("Sample X and y must be same length")

    if test_X is not None:
        # if test_X is set, usually this is for simulation/testing
        if X_bounds is not None:
            raise ValueError("Can't set test_X and X_bounds")

    else:
        # normal case where we randomly sample our test_X
        if X_bounds is None:
            raise ValueError("Must pass in test_X or X_bounds")

    filtered_X, filtered_y = filter_weird_values(sample_X, sample_y)
    # We train our runtime prediction model on *filtered_X* throwing out the sample points with
    # NaN values because they might break our runtime predictor
    runtime_model = None
    if runtimes is not None:
        runtime_filtered_X, runtime_filtered_runtimes = filter_weird_values(
            sample_X, runtimes
        )
        if runtime_filtered_X.shape[0] >= 2:
            runtime_model, runtime_model_mean, runtime_model_stddev = train_runtime_model(
                runtime_filtered_X, runtime_filtered_runtimes
            )
    # We train our failure model on *sample_X*, all the data including NaNs
    # This is *different* than the runtime model.
    failure_model = None
    if failures is not None and sample_X.shape[0] >= 2:
        failure_filtered_X, failure_filtered_runtimes = filter_weird_values(
            sample_X, failures
        )
        if failure_filtered_X.shape[0] >= 2:
            failure_model, failure_model_mean, failure_model_stddev = train_runtime_model(
                failure_filtered_X, failure_filtered_runtimes
            )
    # we can't run this algothim with less than two sample points, so we'll
    # just return a random point
    if filtered_X.shape[0] < 2:
        if test_X is not None:
            # pick a random row from test_X
            row = np.random.choice(test_X.shape[0])
            X = test_X[row, :]
        else:
            X = random_sample(X_bounds, 1)[0]
        if filtered_X.shape[0] < 1:
            prediction = 0.0
        else:
            prediction = filtered_y[0]
        return X, 1.0, prediction, None, None, None, None, None, None

    # build the acquisition function
    gp, y_mean, y_stddev, = train_gaussian_process(
        filtered_X, filtered_y, X_bounds, current_X, nu, max_samples_for_gp
    )
    num_test_samples = 1000
    # Look for the minimum value of our fitted-target-function + (kappa * fitted-target-std_dev)
    if test_X is None:  # this is the usual case
        test_X = random_sample(X_bounds, num_test_samples)
    y_pred, y_pred_std = gp.predict(test_X, return_std=True)
    if failure_model is None:
        prob_of_failure = [0.0] * len(test_X)
    else:
        prob_of_failure = failure_model.predict(
            test_X
        ) * failure_model_stddev + failure_model_mean
    if runtime_model is None:
        expected_runtime = [0.0] * len(test_X)
    else:
        expected_runtime = runtime_model.predict(
            test_X
        ) * runtime_model_stddev + runtime_model_mean
    # best value of y we've seen so far.  i.e. y*
    min_unnorm_y = np.min(filtered_y)
    # hack for dealing with predicted std of 0
    epsilon = 0.00000001
    if opt_func == "probability_of_improvement":
        # might remove the norm_improvement at some point
        # find best chance of an improvement by "at least norm improvement"
        # so if norm_improvement is zero, we are looking for best chance of any
        # improvment over the best result observerd so far.
        #norm_improvement = improvement / y_stddev
        min_norm_y = (min_unnorm_y - y_mean) / y_stddev - improvement
        distance = (y_pred - min_norm_y)
        std_dev_distance = (y_pred - min_norm_y) / (y_pred_std + epsilon)
        prob_of_improve = sigmoid(-std_dev_distance)
        best_test_X_index = np.argmax(prob_of_improve)
    elif opt_func == "expected_improvement":
        min_norm_y = (min_unnorm_y - y_mean) / y_stddev
        Z = -(y_pred - min_norm_y) / (y_pred_std + epsilon)
        prob_of_improve = scipy_stats.norm.cdf(Z)
        e_i = -(y_pred - min_norm_y) * scipy_stats.norm.cdf(Z) + y_pred_std * scipy_stats.norm.pdf(
            Z
        )
        best_test_X_index = np.argmax(e_i)
    # TODO: support expected improvement per time by dividing e_i by runtime
    suggested_X = test_X[best_test_X_index]
    suggested_X_prob_of_improvement = prob_of_improve[best_test_X_index]
    suggested_X_predicted_y = y_pred[best_test_X_index] * y_stddev + y_mean
    unnorm_y_pred = y_pred * y_stddev + y_mean
    unnorm_y_pred_std = y_pred_std * y_stddev
    return (
        suggested_X,
        suggested_X_prob_of_improvement,
        suggested_X_predicted_y,
        test_X,
        unnorm_y_pred,
        unnorm_y_pred_std,
        prob_of_improve,
        prob_of_failure,
        expected_runtime,
    )


def target(x):
    return np.exp(-(x - 2) ** 2) + np.exp(-(x - 6) ** 2 / 10) + 1 / (x ** 2 + 1)


class BayesianSearch(Search):
    def __init__(self, minimum_improvement=0.1):
        self.minimum_improvement = minimum_improvement

    def next_run(self, sweep):
        if 'parameters' not in sweep['config']:
            raise ValueError('Bayesian search requires "parameters" section')
        config = sweep['config']['parameters']
        params = HyperParameterSet.from_config(config)

        sample_X = []
        sample_y = []
        current_X = []
        y = []

        params.index_searchable_params()

        # X_bounds = [[0., 1.]] * len(self.searchable_params)
        # params.numeric_bounds()
        X_bounds = [[0., 1.]] * len(params.searchable_params)

        runs = sweep['runs']

        # we calc the max metric to put as the metric for failed runs
        # so that our bayesian search stays away from them
        max_metric = 0.
        if any(run.state == "finished" for run in runs):
            # for run in runs:
            #    print("DEBUG0", run)
            max_metric = max([self._metric_from_run(sweep['config'], run, default=0.) for run in runs
                              if run.state == "finished"])

        for run in runs:
            X_norm = params.convert_run_to_normalized_vector(run)
            if run.state == "finished":
                # run is complete
                #print("DEBUG0.1", run)
                metric = self._metric_from_run(sweep['config'], run, default=max_metric)
                if math.isnan(metric):
                    metric = max_metric
                y.append(metric)
                sample_X.append(X_norm)
            elif run.state == "running":
                # run is in progress
                # we wont use the metric, but we should pass it into our optimizer to
                # account for the fact that it is running
                current_X.append(X_norm)
            elif run.state == "failed" or run.state == "crashed" or run.state == "killed":
                # run failed, but we're still going to use it
                # maybe we should be smarter about this
                y.append(max_metric)
                sample_X.append(X_norm)
            else:
                raise ValueError("Run is in unknown state")

        if len(sample_X) == 0:
            sample_X = np.empty([0, 0])

        if len(current_X) == 0:
            current_X = None
        else:
            np.array(current_X)
        (try_params, success_prob, pred,
            test_X, y_pred, y_pred_std, prob_of_improve,
            prob_of_failure, expected_runtime) = next_sample(
                np.array(sample_X),
                np.array(y), X_bounds,
                current_X=current_X, improvement=self.minimum_improvement)

        # convert the parameters from vector of [0,1] values
        # to the original ranges

        for param in params:
            if param.type == HyperParameter.CONSTANT:
                continue

            # try_value = try_params[params.param_names_to_index[param.name]]
            # if param.type == HyperParameter.CATEGORICAL:
            #     param.value = param.values[int(try_value)]
            # elif param.type == HyperParameter.INT_UNIFORM:
            #     param.value = int(try_value)
            # elif param.type == HyperParameter.UNIFORM:
            #     param.value = try_value
            try_value = try_params[params.param_names_to_index[param.name]]
            param.value = param.ppf(try_value)

        metric_name = sweep['config']['metric']['name']

        ret_dict = params.to_config()
        info = {}
        info['predictions'] = {metric_name: pred}
        info['success_probability'] = success_prob
        if test_X is not None:
            info['acq_func'] = {}
            info['acq_func']['sample_x'] = params.denormalize_vector(test_X)
            info['acq_func']['y_pred'] = y_pred
            info['acq_func']['y_pred_std'] = y_pred_std
            info['acq_func']['score'] = prob_of_improve

        return ret_dict, info
