import numpy as np

from copy import deepcopy
from typing import List, Tuple, Optional, Union, Dict

from .config.cfg import SweepConfig
from .config.schema import fill_validate_metric
from .run import SweepRun, RunState
from .params import HyperParameter, HyperParameterSet
from sklearn import gaussian_process as sklearn_gaussian
from scipy import stats as scipy_stats

from ._types import floating, integer, ArrayLike

NUGGET = 1e-10


def bayes_baseline_validate_and_fill(config: Dict) -> Dict:
    config = deepcopy(config)

    if "metric" not in config:
        raise ValueError('Bayesian search requires "metric" section')

    if config["method"] != "bayes":
        raise ValueError("Invalid sweep configuration for bayes_search_next_run.")

    config = fill_validate_metric(config)

    return config


def fit_normalized_gaussian_process(
    X: ArrayLike, y: ArrayLike, nu: floating = 1.5
) -> Tuple[sklearn_gaussian.GaussianProcessRegressor, floating, floating]:
    gp = sklearn_gaussian.GaussianProcessRegressor(
        kernel=sklearn_gaussian.kernels.Matern(nu=nu),
        n_restarts_optimizer=2,
        alpha=0.0000001,
        random_state=2,
    )

    y_stddev: ArrayLike
    if len(y) == 1:
        y = np.array(y)
        y_mean = y[0]
        y_stddev = 1.0
    else:
        y_mean = np.mean(y)
        y_stddev = np.std(y) + 0.0001
    y_norm = (y - y_mean) / y_stddev
    gp.fit(X, y_norm)
    return gp, y_mean, y_stddev


def sigmoid(x: ArrayLike) -> ArrayLike:
    return np.exp(-np.logaddexp(0, -x))


def random_sample(X_bounds: ArrayLike, num_test_samples: integer) -> ArrayLike:
    if hasattr(X_bounds, "tolist"):
        X_bounds = X_bounds.tolist()
    num_hyperparameters = len(X_bounds)
    test_X = np.empty((int(num_test_samples), num_hyperparameters))
    for ii in range(num_test_samples):
        for jj in range(num_hyperparameters):
            if type(X_bounds[jj][0]) == int:
                assert type(X_bounds[jj][1]) == int
                test_X[ii, jj] = np.random.randint(X_bounds[jj][0], X_bounds[jj][1])
            else:
                test_X[ii, jj] = (
                    np.random.uniform() * (X_bounds[jj][1] - X_bounds[jj][0])
                    + X_bounds[jj][0]
                )
    return test_X


def predict(
    X: ArrayLike, y: ArrayLike, test_X: ArrayLike, nu: floating = 1.5
) -> Tuple[ArrayLike, ArrayLike]:
    gp, norm_mean, norm_stddev = fit_normalized_gaussian_process(X, y, nu=nu)
    y_pred, y_std = gp.predict([test_X], return_std=True)
    y_std_norm = y_std * norm_stddev
    y_pred_norm = (y_pred * norm_stddev) + norm_mean
    return y_pred_norm[0], y_std_norm[0]


def train_gaussian_process(
    sample_X: ArrayLike,
    sample_y: ArrayLike,
    X_bounds: Optional[ArrayLike] = None,
    current_X: ArrayLike = None,
    nu: floating = 1.5,
    max_samples: integer = 100,
) -> Tuple[sklearn_gaussian.GaussianProcessRegressor, floating, floating]:
    """Trains a Gaussian Process function from sample_X, sample_y data.

    Handles the case where there are other training runs in flight (current_X)

    Arguments:
        sample_X: vector of already evaluated sets of hyperparameters
        sample_y: vector of already evaluated loss function values
        X_bounds: minimum and maximum values for every dimension of X
        current_X: hyperparameters currently being explored
        nu: input to the Matern function, higher numbers make it smoother 0.5, 1.5, 2.5 are good values
         see http://scikit-learn.org/stable/modules/generated/sklearn.gaussian_process.kernels.Matern.html

    Returns:
        gp: the gaussian process function
        y_mean: mean
        y_stddev: stddev

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
            current_X = current_X[: (max_samples - 5), :]  # type: ignore
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


def filter_nans(sample_X: ArrayLike, sample_y: ArrayLike) -> ArrayLike:
    is_row_finite = ~(np.isnan(sample_X).any(axis=1) | np.isnan(sample_y))
    sample_X = sample_X[is_row_finite, :]
    sample_y = sample_y[is_row_finite]
    return sample_X, sample_y


def next_sample(
    *,
    sample_X: ArrayLike,
    sample_y: ArrayLike,
    X_bounds: Optional[ArrayLike] = None,
    current_X: Optional[ArrayLike] = None,
    nu: floating = 1.5,
    max_samples_for_model: integer = 100,
    improvement: floating = 0.1,
    bw_multiplier=0.2,
    num_points_to_try: integer = 1000,
    opt_func: str = "expected_improvement",
    model: str = "gp",
    test_X: Optional[ArrayLike] = None,
) -> Tuple[ArrayLike, floating, floating, floating, floating]:
    """Calculates the best next sample to look at via bayesian optimization.

    Args:
        sample_X: ArrayLike, shape (N_runs, N_params)
            2d array of already evaluated sets of hyperparameters
        sample_y: ArrayLike, shape (N_runs,)
            1d array of already evaluated loss function values
        X_bounds: ArrayLike, optional, shape (N_params, 2), default None
            2d array minimum and maximum values for every dimension of X
        current_X: ArrayLike, optional, shape (N_runs_in_flight, N_params), default None
            hyperparameters currently being explored
        nu: floating, optional, default = 1.5
            input to the Matern function, higher numbers make it smoother. 0.5,
            1.5, 2.5 are good values  see

               http://scikit-learn.org/stable/modules/generated/sklearn.gaussian_process.kernels.Matern.html

        max_samples_for_model: integer, optional, default 100
            maximum samples to consider (since algo is O(n^3)) for performance,
            but also adds some randomness. this number of samples will be chosen
            randomly from the sample_X and used to train the GP.
        improvement: floating, optional, default 0.1
            amount of improvement to optimize for -- higher means take more exploratory risks
        bw_multiplier: floating, optional, default 0.2
            scaling factor for kernel density estimation bandwidth for tpe_multi algorithm
        num_points_to_try: integer, optional, default 1000
            number of X values to try when looking for value with highest expected probability
            of improvement
        opt_func: one of {"expected_improvement", "prob_of_improvement"} - whether to optimize expected
                improvement of probability of improvement.  Expected improvement is generally better - may want
                to remove probability of improvement at some point.  (But I think prboability of improvement
                is a little easier to calculate)
        model: one of {"gp", "tpe", "tpe_multi"} - whether to use a Gaussian Process as a surrogate model,
            a Tree-structured Parzen Estimator, or a multivariate TPE
        test_X: X values to test when looking for the best values to try

    Returns:
        suggested_X: optimal X value to try
        prob_of_improvement: probability of an improvement
        predicted_y: predicted value
        predicted_std: stddev of predicted value
        expected_improvement: expected improvement
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

    filtered_X, filtered_y = filter_nans(sample_X, sample_y)

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
        return (
            X,
            1.0,
            prediction,
            np.nan,
            np.nan,
        )

    if model == "bayes-tpe":
        return next_sample_tpe(
            filtered_X=filtered_X,
            filtered_y=filtered_y,
            X_bounds=X_bounds,
            current_X=current_X,
            max_samples_for_model=max_samples_for_model,
            improvement=improvement,
            num_points_to_try=num_points_to_try,
            test_X=test_X,
            multivariate=False,
        )
    elif model == "bayes-tpe-multi":
        return next_sample_tpe(
            filtered_X=filtered_X,
            filtered_y=filtered_y,
            X_bounds=X_bounds,
            current_X=current_X,
            max_samples_for_model=max_samples_for_model,
            improvement=improvement,
            num_points_to_try=num_points_to_try,
            test_X=test_X,
            multivariate=True,
            bw_multiplier=bw_multiplier,
        )
    else:  # GP
        return next_sample_gp(
            filtered_X=filtered_X,
            filtered_y=filtered_y,
            X_bounds=X_bounds,
            current_X=current_X,
            nu=nu,
            max_samples_for_model=max_samples_for_model,
            improvement=improvement,
            num_points_to_try=num_points_to_try,
            opt_func=opt_func,
            test_X=test_X,
        )


def next_sample_gp(
    filtered_X: ArrayLike,
    filtered_y: ArrayLike,
    X_bounds: Optional[ArrayLike] = None,
    current_X: Optional[ArrayLike] = None,
    nu: floating = 1.5,
    max_samples_for_model: integer = 100,
    improvement: floating = 0.01,
    num_points_to_try: integer = 1000,
    opt_func: str = "expected_improvement",
    test_X: Optional[ArrayLike] = None,
) -> Tuple[ArrayLike, floating, floating, floating, floating]:
    # build the acquisition function
    gp, y_mean, y_stddev, = train_gaussian_process(
        filtered_X, filtered_y, X_bounds, current_X, nu, max_samples_for_model
    )
    # Look for the minimum value of our fitted-target-function + (kappa * fitted-target-std_dev)
    if test_X is None:  # this is the usual case
        test_X = random_sample(X_bounds, num_points_to_try)
    y_pred, y_pred_std = gp.predict(test_X, return_std=True)

    # best value of y we've seen so far.  i.e. y*
    min_unnorm_y = np.min(filtered_y)
    # hack for dealing with predicted std of 0
    epsilon = 0.00000001

    """
    if opt_func == "probability_of_improvement":
        min_norm_y = (min_unnorm_y - y_mean) / y_stddev - improvement
    else:
    """
    min_norm_y = (min_unnorm_y - y_mean) / y_stddev

    Z = -(y_pred - min_norm_y) / (y_pred_std + epsilon)
    prob_of_improve: np.ndarray = scipy_stats.norm.cdf(Z)
    e_i = -(y_pred - min_norm_y) * scipy_stats.norm.cdf(
        Z
    ) + y_pred_std * scipy_stats.norm.pdf(Z)

    """
    if opt_func == "probability_of_improvement":
        best_test_X_index = np.argmax(prob_of_improve)
    else:
    """
    best_test_X_index = np.argmax(e_i)

    suggested_X = test_X[best_test_X_index]
    suggested_X_prob_of_improvement = prob_of_improve[best_test_X_index]
    suggested_X_predicted_y = y_pred[best_test_X_index] * y_stddev + y_mean
    suggested_X_predicted_std = y_pred_std[best_test_X_index] * y_stddev

    # recalculate expected improvement
    min_norm_y = (min_unnorm_y - y_mean) / y_stddev
    z_best = -(y_pred[best_test_X_index] - min_norm_y) / (
        y_pred_std[best_test_X_index] + epsilon
    )
    suggested_X_expected_improvement = -(
        y_pred[best_test_X_index] - min_norm_y
    ) * scipy_stats.norm.cdf(z_best) + y_pred_std[
        best_test_X_index
    ] * scipy_stats.norm.pdf(
        z_best
    )

    return (
        suggested_X,
        suggested_X_prob_of_improvement,
        suggested_X_predicted_y,
        suggested_X_predicted_std,
        suggested_X_expected_improvement,
    )


def fit_parzen_estimator_scott_bw(X, X_bounds, multiplier=1.06):
    extended_X = np.insert(X_bounds.T, 1, X, axis=0)
    mu = np.mean(extended_X, axis=0)
    sumsqrs = np.sum(np.square(extended_X - mu), axis=0)
    sigmahat = np.sqrt(sumsqrs / (len(extended_X) - 1))
    sigmas = multiplier * sigmahat * len(extended_X) ** (-1.0 / (4.0 + len(X_bounds)))
    return np.tile(sigmas, [len(X), 1])


def fit_1D_parzen_estimator_heuristic_bw(X, X_bounds):
    sorted_ind = np.argsort(X.copy())
    sorted_mus = X[sorted_ind]

    # Treat endpoints of interval as data points
    # extended_mus = np.insert(X_bounds, 1, sorted_mus)

    # Ignore endpoints of interval
    extended_mus = np.insert([sorted_mus[0], sorted_mus[-1]], 1, sorted_mus)

    sigmas = np.zeros(len(X))
    sigmas[sorted_ind] = np.maximum(
        extended_mus[2:] - extended_mus[1:-1], extended_mus[1:-1] - extended_mus[0:-2]
    )

    # Magic formula from reference implementation
    prior_sigma = (X_bounds[1] - X_bounds[0]) / np.sqrt(12.0)
    minsigma = prior_sigma / min(100.0, (1.0 + len(X)))
    sigmas = np.clip(sigmas, minsigma, prior_sigma)

    return sigmas


def sample_from_parzen_estimator(mus, sigmas, X_bounds, num_samples):
    indices = np.random.default_rng().integers(-1, len(mus), num_samples)
    samples = np.zeros((num_samples, len(X_bounds)))
    uniform_ind = indices == -1
    num_uniform = np.count_nonzero(uniform_ind)
    samples[uniform_ind] = np.random.default_rng().uniform(
        np.tile(X_bounds[:, 0], [num_uniform, 1]),
        np.tile(X_bounds[:, 1], [num_uniform, 1]),
    )
    normal_ind = indices >= 0
    samples[normal_ind] = np.random.default_rng().normal(
        loc=mus[indices[normal_ind]], scale=sigmas[indices[normal_ind]]
    )
    return np.clip(samples, X_bounds[:, 0], X_bounds[:, 1])


def sample_from_1D_parzen_estimator(mus, sigmas, X_bounds, num_points_to_try):
    indices = np.random.default_rng().integers(-1, len(mus), num_points_to_try)
    new_samples = np.zeros(num_points_to_try)

    # For which_mu == -1, sample from the (uniform) prior
    new_samples[indices == -1] = np.random.default_rng().uniform(
        X_bounds[0], X_bounds[1], np.sum(indices == -1)
    )
    # Other samples are from mus
    new_samples[indices >= 0] = np.random.default_rng().normal(
        loc=mus[indices[indices >= 0]], scale=sigmas[indices[indices >= 0]]
    )
    return np.clip(new_samples, X_bounds[0], X_bounds[1])


def llik_from_parzen_estimator(samples, mus, sigmas, X_bounds):
    samp_norm = (np.tile(samples, [len(mus), 1, 1]).transpose((1, 0, 2)) - mus) / sigmas
    samp_norm = np.square(samp_norm)
    normalization = (2.0 * np.pi) ** (-len(X_bounds) / 2.0) / np.prod(sigmas, axis=1)
    pdf = normalization * np.exp(-0.5 * np.sum(samp_norm, axis=2))
    uniform_pdf = 1.0 / np.prod(X_bounds[:, 1] - X_bounds[:, 0])
    mixture = (np.sum(pdf, axis=1) + uniform_pdf) / (len(mus) + 1.0)
    return np.log(mixture)


def llik_from_1D_parzen_estimator(samples, mus, sigmas, X_bounds):
    samp_norm = (np.tile(samples, [len(mus), 1]).T - mus) / sigmas
    llik = np.log(
        (
            np.sum(scipy_stats.norm.pdf(samp_norm) / sigmas, axis=1)
            + 1.0 / (X_bounds[1] - X_bounds[0])
        )
        / (len(mus) + 1.0)
    )
    return llik


def parzen_threshold(y, gamma):
    num_low = int(np.ceil(gamma * np.sqrt(len(y))))
    low_ind = np.argsort(y)[0:num_low]
    ret_val = np.array([False] * len(y))
    ret_val[low_ind] = True
    return ret_val


def next_sample_tpe(
    filtered_X: ArrayLike,
    filtered_y: ArrayLike,
    X_bounds: Optional[ArrayLike] = None,
    current_X: Optional[ArrayLike] = None,
    max_samples_for_model: integer = 100,
    improvement: floating = 0.01,
    num_points_to_try: integer = 1000,
    test_X: Optional[ArrayLike] = None,
    multivariate: Optional[bool] = False,
    bw_multiplier: Optional[floating] = 1.0,
) -> Tuple[ArrayLike, floating, floating, floating, floating]:

    if X_bounds is None:
        hp_min = np.min(filtered_X, axis=0)
        hp_max = np.max(filtered_X, axis=0)
        X_bounds = np.column_stack(hp_min, hp_max)
    else:
        X_bounds = np.array(X_bounds)

    low_ind = parzen_threshold(filtered_y, improvement)
    low_X = filtered_X[low_ind]
    high_X = filtered_X[np.logical_not(low_ind)]
    num_hp = len(X_bounds)
    if multivariate:
        low_mus = low_X.copy()
        high_mus = high_X.copy()

        low_sigmas = fit_parzen_estimator_scott_bw(low_X, X_bounds, bw_multiplier)
        high_sigmas = fit_parzen_estimator_scott_bw(high_X, X_bounds)

        new_samples = sample_from_parzen_estimator(
            low_mus, low_sigmas, X_bounds, num_points_to_try
        )
        low_llik = llik_from_parzen_estimator(
            new_samples, low_mus, low_sigmas, X_bounds
        )
        high_llik = llik_from_parzen_estimator(
            new_samples, high_mus, high_sigmas, X_bounds
        )
        score = low_llik - high_llik
        best_sample = new_samples[np.argmax(score), :]
    else:
        # Fit separate 1D Parzen estimators to each hyperparameter
        best_sample = np.zeros(num_hp)
        for i in range(num_hp):
            low_mus = low_X[:, i]
            high_mus = high_X[:, i]
            low_sigmas = fit_1D_parzen_estimator_heuristic_bw(low_mus, X_bounds[i])
            high_sigmas = fit_1D_parzen_estimator_heuristic_bw(high_mus, X_bounds[i])
            new_samples = sample_from_1D_parzen_estimator(
                low_mus, low_sigmas, X_bounds[i], num_points_to_try
            )
            low_llik = llik_from_1D_parzen_estimator(
                new_samples, low_mus, low_sigmas, X_bounds[i]
            )
            high_llik = llik_from_1D_parzen_estimator(
                new_samples, high_mus, high_sigmas, X_bounds[i]
            )
            best_sample[i] = new_samples[np.argmax(low_llik - high_llik)]

    # TODO: replace nans with actual values
    return (
        best_sample,
        np.nan,
        np.nan,
        np.nan,
        np.nan,
    )


def _construct_bayes_data(
    runs: List[SweepRun], config: Union[dict, SweepConfig]
) -> Tuple[HyperParameterSet, ArrayLike, ArrayLike, ArrayLike]:
    goal = config["metric"]["goal"]
    metric_name = config["metric"]["name"]
    worst_func = min if goal == "maximize" else max
    params = HyperParameterSet.from_config(config["parameters"])

    if len(params.searchable_params) == 0:
        raise ValueError("Need at least one searchable parameter for bayes search.")

    sample_X: ArrayLike = []
    current_X: ArrayLike = []
    y: ArrayLike = []

    # we calc the max metric to put as the metric for failed runs
    # so that our bayesian search stays away from them
    worst_metric: floating = np.inf if goal == "maximize" else -np.inf
    for run in runs:
        if run.state == RunState.finished:
            try:
                run_extremum = run.metric_extremum(
                    metric_name, kind="minimum" if goal == "maximize" else "maximum"
                )
            except ValueError:
                run_extremum = 0.0  # default
            worst_metric = worst_func(worst_metric, run_extremum)
    if not np.isfinite(worst_metric):
        worst_metric = 0.0

    X_norms = params.convert_runs_to_normalized_vector(runs)
    for run, X_norm in zip(runs, X_norms):
        if run.state == RunState.finished:
            try:
                metric = run.metric_extremum(
                    metric_name, kind="maximum" if goal == "maximize" else "minimum"
                )
            except ValueError:
                metric = worst_metric  # default
            y.append(metric)
            sample_X.append(X_norm)
        elif run.state in [
            RunState.running,
            RunState.preempting,
            RunState.preempted,
            RunState.pending,
        ]:
            # run is in progress
            # we wont use the metric, but we should pass it into our optimizer to
            # account for the fact that it is running
            current_X.append(X_norm)
        elif run.state in [RunState.failed, RunState.crashed, RunState.killed]:
            # run failed, but we're still going to use it
            # maybe we should be smarter about this
            y.append(worst_metric)
            sample_X.append(X_norm)
        else:
            raise ValueError("Run is in unknown state")

    if len(sample_X) == 0:
        sample_X = np.empty([0, 0])
    else:
        sample_X = np.asarray(sample_X)

    if len(current_X) > 0:
        current_X = np.array(current_X)

    # impute bad metric values from y
    y = np.asarray(y)
    if len(y) > 0:
        y[~np.isfinite(y)] = worst_metric

    # next_sample is a minimizer, so if we are trying to
    # maximize, we need to negate y
    y *= -1 if goal == "maximize" else 1

    return params, sample_X, current_X, y


def bayes_search_next_run(
    runs: List[SweepRun],
    config: Union[dict, SweepConfig],
    validate: bool = False,
    minimum_improvement: floating = 0.1,
) -> SweepRun:
    """Suggest runs using Bayesian optimization.

    >>> suggestion = bayes_search_next_run([], {
    ...    'method': 'bayes',
    ...    'parameters': {'a': {'min': 1., 'max': 2.}},
    ...    'metric': {'name': 'loss', 'goal': 'maximize'}
    ... })

    Args:
        runs: The runs in the sweep.
        config: The sweep's config.
        minimum_improvement: The minimium improvement to optimize for. Higher means take more exploratory risks.
        validate: Whether to validate `sweep_config` against the SweepConfig JSONschema.
           If true, will raise a Validation error if `sweep_config` does not conform to
           the schema. If false, will attempt to run the sweep with an unvalidated schema.

    Returns:
        The suggested run.
    """

    if validate:
        config = SweepConfig(config)

    if "metric" not in config:
        raise ValueError('Bayesian search requires "metric" section')

    if "method" not in config:
        raise ValueError("Method must be specified")

    if config["method"] not in ["bayes", "bayes-tpe", "bayes-tpe-multi"]:
        raise ValueError(
            'Invalid method for bayes_search_next_run, must be one of "bayes", "bayes-tpe", "bayes-tpe-multi"'
        )

    params, sample_X, current_X, y = _construct_bayes_data(runs, config)
    X_bounds = [[0.0, 1.0]] * len(params.searchable_params)

    (
        suggested_X,
        suggested_X_prob_of_improvement,
        suggested_X_predicted_y,
        suggested_X_predicted_std,
        suggested_X_expected_improvement,
    ) = next_sample(
        sample_X=sample_X,
        sample_y=y,
        X_bounds=X_bounds,
        current_X=current_X if len(current_X) > 0 else None,
        model=config["method"],
        improvement=minimum_improvement,
    )

    # convert the parameters from vector of [0,1] values
    # to the original ranges
    for param in params:
        if param.type == HyperParameter.CONSTANT:
            continue
        try_value = suggested_X[params.param_names_to_index[param.name]]
        param.value = param.ppf(try_value)

    ret_dict = params.to_config()
    info = {
        "success_probability": suggested_X_prob_of_improvement,
        "predicted_value": suggested_X_predicted_y,
        "predicted_value_std_dev": suggested_X_predicted_std,
        "expected_improvement": suggested_X_expected_improvement,
    }
    return SweepRun(config=ret_dict, search_info=info)


def bayes_search_next_runs(
    runs: List[SweepRun],
    config: Union[dict, SweepConfig],
    validate: bool = False,
    n: int = 1,
    minimum_improvement: floating = 0.1,
):
    ret: List[SweepRun] = []
    for _ in range(n):
        suggestion = bayes_search_next_run(
            runs + ret, config, validate, minimum_improvement
        )
        ret.append(suggestion)
    return ret
