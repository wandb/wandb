"""
Hyperparameter search saved from the old flex service.
"""
import itertools
import random
from . import bayes, early_terminate
import numpy as np
import math
import scipy.stats as stats


class Search():
    @staticmethod
    def to_class(config):
        method = config.get('method')
        if method is None:
            raise ValueError('config missing required "method" field.')
        method = method.lower()
        if method == 'grid':
            return GridSearch()
        elif method == 'bayes':
            return BayesianSearch()
        elif method == 'random':
            return RandomSearch()
        raise ValueError('method "%s" is not supported' % config['method'])

    def _load_early_terminate_from_config(self, sweep_config):
        if not 'early_terminate' in sweep_config:
            return None

        et_config = sweep_config['early_terminate']
        if not 'type' in et_config:
            raise ValueError("Didn't specify early terminate type")

        if et_config['type'] == 'envelope':
            kw_args = {}
            if 'fraction' in et_config:
                kw_args['fraction'] = et_config['fraction']
            if 'min_runs' in et_config:
                kw_args['min_runs'] = et_config['min_runs']
            if 'start_iter' in et_config:
                kw_args['start_iter'] = et_config['start_iter']

            return EnvelopeEarlyTerminate(**kw_args)
        elif et_config['type'] == 'hyperband':
            # one way of defining hyperband, with max_iter, s and possibly eta
            if 'max_iter' in et_config:
                max_iter = et_config['max_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']

                s = 0
                if 's' in et_config:
                    s = et_config['s']
                else:
                    raise "Must define s for hyperband algorithm if max_iter is defined"

                return HyperbandEarlyTerminate.init_from_max_iter(max_iter, eta, s)
            # another way of defining hyperband with min_iter and possibly eta
            if 'min_iter' in et_config:
                min_iter = et_config['min_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']
                return HyperbandEarlyTerminate.init_from_min_iter(min_iter, eta)


        else:
            raise 'unsupported early termination type %s'.format(
                et_config['type'])

    def _metric_from_run(self, sweep_config, run):
        metric_name = sweep_config['metric']['name']

        maximize = False
        if 'goal' in sweep_config['metric']:
            if sweep_config['metric']['goal'] == 'maximize':
                maximize = True

        if metric_name in run.summaryMetrics:
            metric = run.summaryMetrics[metric_name]
        else:
            # maybe should do something other than erroring
            raise ValueError(
                "Couldn't find summary metric {}".format(metric_name))

        if maximize:
            metric = -metric

        return metric

    def next_run(self, sweep):
        """Called each time an agent requests new work.
        Args:
            sweep: <defined above>
        Returns:
            None if all work complete for this sweep. A dictionary of configuration
            parameters for the next run.
        """
        raise NotImplementedError

    def stop_runs(self, sweep):
        """Choose which runs to early stop if applicable.
        This will be called from a cron job every 30 seconds.
        Args:
            sweep: <defined above>
        Returns:
            Return the list of run names to early stop, empty list if there are no
            runs to stop now.
        """
        early_terminate = self._load_early_terminate_from_config(
            sweep['config'])
        if early_terminate is None:
            return []
        else:
            return early_terminate.stop_runs(sweep['config'], sweep['runs'])


class HyperParameter():
    CONSTANT = 0
    CATEGORICAL = 1
    INT_UNIFORM = 2
    UNIFORM = 3
    LOG_UNIFORM = 4
    Q_UNIFORM = 5
    Q_LOG_UNIFORM = 6
    NORMAL = 7
    Q_NORMAL = 8
    LOG_NORMAL = 9
    Q_LOG_NORMAL = 10

    def _load_parameter(self, param_config, param_name):
        if param_name in param_config:
            setattr(self, param_name, param_config[param_name])
        else:
            raise ValueError(f"Need to specify {param_name} \
                with distribution: {param_config['distribution']}.")

    def _load_optional_parameter(self, param_config, param_name, default_value):
        if param_name in param_config:
            setattr(self, param_name, param_config[param_name])
        else:
            setattr(self, param_name, default_value)

    def __init__(self, param_name, param_config):

        self.name = param_name
        self.config = param_config.copy()

        allowed_config_keys = set(['distribution', 'value', 'values', 'min', 'max', 'q',
                                   'mu', 'sigma', 'desc'])
        for key in self.config.keys():
            if key not in allowed_config_keys:
                raise ValueError(
                    f"Unexpected hyperparameter configuration {key}")

        self.type = None
        if 'distribution' in self.config:
            self.distribution = self.config['distribution']
            if self.distribution == 'constant':
                self.type = HyperParameter.CONSTANT
                self._load_parameter(self.config, 'value')
            elif self.distribution == 'categorical':
                self.type = HyperParameter.CATEGORICAL
                self._load_parameter(self.config, 'values')
            elif self.distribution == 'int_uniform':
                self.type = HyperParameter.INT_UNIFORM
                self._load_parameter(self.config, 'min')
                self._load_parameter(self.config, 'max')
            elif self.distribution == 'uniform':
                self.type = HyperParameter.UNIFORM
                self._load_parameter(self.config, 'min')
                self._load_parameter(self.config, 'max')
            elif self.distribution == 'q_uniform':
                self.type = HyperParameter.Q_UNIFORM
                self._load_parameter(self.config, 'min')
                self._load_parameter(self.config, 'max')
                self._load_optional_parameter(self.config, 'q', 1.0)
            elif self.distribution == 'log_uniform':
                self.type = HyperParameter.LOG_UNIFORM
                self._load_parameter(self.config, 'min')
                self._load_parameter(self.config, 'max')
            elif self.distribution == 'q_log_uniform':
                self.type = HyperParameter.Q_LOG_UNIFORM
                self._load_parameter(self.config, 'min')
                self._load_parameter(self.config, 'max')
                self._load_optional_parameter(self.config, 'q', 1.0)
            elif self.distribution == 'normal':
                self.type = HyperParameter.NORMAL
                self._load_optional_parameter(self.config, 'mu', 0.0)
                self._load_optional_parameter(self.config, 'sigma', 1.0)
                # need or set mean and stddev
            elif self.distribution == 'q_normal':
                self.type = HyperParameter.Q_NORMAL
                self._load_optional_parameter(self.config, 'mu', 0.0)
                self._load_optional_parameter(self.config, 'sigma', 1.0)
                self._load_optional_parameter(self.config, 'q', 1.0)
            elif self.distribution == 'log_normal':
                self.type = HyperParameter.LOG_NORMAL
                self._load_optional_parameter(self.config, 'mu', 0.0)
                self._load_optional_parameter(self.config, 'sigma', 1.0)
                # need or set mean and stdev
            elif self.distribution == 'q_log_normal':
                self.type = HyperParameter.Q_LOG_NORMAL
                self._load_optional_parameter(self.config, 'mu', 0.0)
                self._load_optional_parameter(self.config, 'sigma', 1.0)
                self._load_optional_parameter(self.config, 'q', 1.0)
                # need or set mean and stdev
            else:
                raise ValueError(
                    f"Unsupported distribution: {self.distribution}")

            if 'q' in dir(self):
                if self.q < 0.0:
                    raise ValueError('q must be positive.')
            if 'sigma' in dir(self):
                if self.sigma < 0.0:
                    raise ValueError('sigma must be positive.')
            if ('min' in dir(self) and 'max' in dir(self)):
                if self.min >= self.max:
                    raise ValueError('max must be greater than min.')
        else:
            self._infer_distribution(self.config, param_name)

    def value_to_int(self, value):
        if self.type != HyperParameter.CATEGORICAL:
            raise ValueError(
                "Can only call value_to_int on categorical variable")

        for ii, test_value in enumerate(self.values):
            if (value == test_value):
                return ii

        raise ValueError("Couldn't find {}".format(value))

    def cdf(self, x):
        """
        Percent point function or inverse cdf
        Inputs: sample from selected distribution at the xth percentile.
        Ouputs: float in the range [0, 1]
        """
        if self.type == HyperParameter.CONSTANT:
            return 0.0
        elif self.type == HyperParameter.CATEGORICAL:
            return stats.randint.cdf(self.values.index(x), 0, len(self.values))
        elif self.type == HyperParameter.INT_UNIFORM:
            return stats.randint.cdf(x, self.min, self.max + 1)
        elif (self.type == HyperParameter.UNIFORM or
                self.type == HyperParameter.Q_UNIFORM):
            return stats.uniform.cdf(x, self.min, self.max - self.min)
        elif (self.type == HyperParameter.LOG_UNIFORM or
                self.type == HyperParameter.Q_LOG_UNIFORM):
            return stats.uniform.cdf(np.log(x), self.min, self.max - self.min)
        elif (self.type == HyperParameter.NORMAL or
                self.type == HyperParameter.Q_NORMAL):
            return stats.norm.cdf(x, loc=self.mu, scale=self.sigma)
        elif (self.type == HyperParameter.LOG_NORMAL or
                self.type == HyperParameter.Q_LOG_NORMAL):
            return stats.lognorm.cdf(x, s=self.sigma, scale=np.exp(self.mu))
        else:
            raise ValueError("Unsupported hyperparameter distribution type")

    def ppf(self, x):
        """
        Percent point function or inverse cdf
        Inputs: x: float in range [0, 1]
        Ouputs: sample from selected distribution at the xth percentile.
        """
        if x < 0.0 or x > 1.0:
            raise ValueError("Can't call ppf on value outside of [0,1]")
        if self.type == HyperParameter.CONSTANT:
            return self.value
        elif self.type == HyperParameter.CATEGORICAL:
            return self.values[int(stats.randint.ppf(x, 0, len(self.values)))]
        elif self.type == HyperParameter.INT_UNIFORM:
            return int(stats.randint.ppf(x, self.min, self.max + 1))
        elif self.type == HyperParameter.UNIFORM:
            return stats.uniform.ppf(x, self.min, self.max - self.min)
        elif self.type == HyperParameter.Q_UNIFORM:
            r = stats.uniform.ppf(x, self.min, self.max - self.min)
            ret_val = np.round(r / self.q) * self.q
            if type(self.q) == int:
                return int(ret_val)
            else:
                return ret_val
        elif self.type == HyperParameter.LOG_UNIFORM:
            return np.exp(stats.uniform.ppf(x, self.min, self.max - self.min))
        elif self.type == HyperParameter.Q_LOG_UNIFORM:
            r = np.exp(stats.uniform.ppf(x, self.min, self.max - self.min))
            ret_val = np.round(r / self.q) * self.q
            if type(self.q) == int:
                return int(ret_val)
            else:
                return ret_val
        elif self.type == HyperParameter.NORMAL:
            return stats.norm.ppf(x, loc=self.mu, scale=self.sigma)
        elif self.type == HyperParameter.Q_NORMAL:
            r = stats.norm.ppf(x, loc=self.mu, scale=self.sigma)
            ret_val = np.round(r / self.q) * self.q
            if type(self.q) == int:
                return int(ret_val)
            else:
                return ret_val
        elif self.type == HyperParameter.LOG_NORMAL:
            # https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.lognorm.html
            return stats.lognorm.ppf(x, s=self.sigma, scale=np.exp(self.mu))
        elif self.type == HyperParameter.Q_LOG_NORMAL:
            r = stats.lognorm.ppf(x, s=self.sigma, scale=np.exp(self.mu))
            ret_val = np.round(r / self.q) * self.q

            if type(self.q) == int:
                return int(ret_val)
            else:
                return ret_val
        else:
            raise ValueError("Unsupported hyperparameter distribution type")

    def sample(self):
        return self.ppf(random.uniform(0.0, 1.0))
        # if self.type == HyperParameter.CONSTANT:
        #     return self.value
        # elif self.type == HyperParameter.CATEGORICAL:
        #     return random.choice(self.values)
        # elif self.type == HyperParameter.INT_UNIFORM:
        #     return random.randint(self.min, self.max)
        # elif self.type == HyperParameter.UNIFORM:
        #     return random.uniform(self.min, self.max)
        # elif self.type == HyperParameter.Q_UNIFORM:
        #     x = random.uniform(self.min, self.max)
        #     return np.round(x / self.q) * self.q
        # elif self.type == HyperParameter.LOG_UNIFORM:
        #     return np.exp(random.uniform(self.min, self.max))
        # elif self.type == HyperParameter.Q_LOG_UNIFORM:
        #     x = random.uniform(self.min, self.max)
        #     return np.round(np.exp(x) / self.q) * self.q
        # elif self.type == HyperParameter.NORMAL:
        #     return random.normal(loc=self.mu, scale=self.sigma)
        # elif self.type == HyperParameter.Q_NORMAL:
        #     x = random.normal(loc=self.mu, scale=self.sigma)
        #     return np.round(x / self.q) * self.q
        # elif self.type == HyperParameter.LOG_NORMAL:
        #     return np.exp(self.mu + self.sigma * random.normal())
        # elif self.type == HyperParameter.Q_LOG_NORMAL:
        #     x = random.normal(loc=self.mu, scale=self.sigma)
        #     return np.round(np.exp(x) / self.q) * self.q
        # else:
        #     raise ValueError("Unsupported hyperparameter distribution type")

    def to_config(self):
        if self.value != None:
            self.config['value'] = self.value
            # Remove values list if we have picked a value for this parameter
            self.config.pop('values', None)
        return self.name, self.config

    def _infer_distribution(self, config, param_name):
        """
        Attempt to automatically figure out the distribution if it's not specified.
            1) If the values are set, assume categorical.
            2) If the min and max are floats, assume uniform.
            3) If the min and max are ints, assume int_uniform.
        """
        if 'values' in config:
            self.type = HyperParameter.CATEGORICAL
            self.values = config['values']
        elif 'min' in config:
            if not 'max' in config:
                raise ValueError(
                    f"Need to have a max with a min or specify the distribution for parameter {param_name}")
            self.min = config['min']
            self.max = config['max']

            if type(config['min']) == int and type(config['max']) == int:
                self.type = HyperParameter.INT_UNIFORM
            elif type(config['min']) in (int, float) and type(config['max']) in (int, float):
                self.type = HyperParameter.UNIFORM
            else:
                raise ValueError(
                    f"Min and max must be type int or float for parameter {param_name}")

        elif 'value' in config:
            self.type = HyperParameter.CONSTANT
            self.value = config['value']
        else:
            raise ValueError(f"Bad configuration for parameter: {param_name}")


class HyperParameterSet(set):
    @staticmethod
    def from_config(config):
        hpd = HyperParameterSet([HyperParameter(param_name, param_config)
                                 for param_name, param_config in config.items()])
        return hpd

    def to_config(self):
        return dict([param.to_config() for param in list(self)])

    def index_searchable_params(self):
        self.searchable_params = [
            param for param in self if param.type != HyperParameter.CONSTANT]

        self.param_names_to_index = {}
        self.param_names_to_param = {}

        for ii, param in enumerate(self.searchable_params):
            self.param_names_to_index[param.name] = ii
            self.param_names_to_param[param.name] = param

    def numeric_bounds(self):
        """
        Gets a set of numeric minimums and maximums for doing ml
        predictions on the hyperparameters

        """
        self.searchable_params = [
            param for param in self if param.type != HyperParameter.CONSTANT]

        X_bounds = [[0., 0.]] * len(self.searchable_params)

        self.param_names_to_index = {}
        self.param_names_to_param = {}

        for ii, param in enumerate(self.searchable_params):
            self.param_names_to_index[param.name] = ii
            self.param_names_to_param[param.name] = param
            if param.type == HyperParameter.CATEGORICAL:
                X_bounds[ii] = [0, len(param.values)]
            elif param.type == HyperParameter.INT_UNIFORM:
                X_bounds[ii] = [param.min, param.max]
            elif param.type == HyperParameter.UNIFORM:
                X_bounds[ii] = [param.min, param.max]
            else:
                raise ValueError("Unsupported param type")

        return X_bounds

    def convert_run_to_vector(self, run):
        """
        Converts run parameters to vectors.
        Should be able to remove.

        """

        run_params = run.config or {}
        X = np.zeros([len(self.searchable_params)])

        # we ignore keys we haven't seen in our spec
        # we don't handle the case where a key is missing from run config
        for key, config_value in run_params.items():
            if key in self.param_names_to_index:
                param = self.param_names_to_param[key]
                bayes_opt_index = self.param_names_to_index[key]
                if param.type == HyperParameter.CATEGORICAL:
                    bayes_opt_value = param.value_to_int(config_value["value"])
                else:
                    bayes_opt_value = config_value["value"]

                X[bayes_opt_index] = bayes_opt_value
        return X

    def denormalize_vector(self, X):
        """Converts a list of vectors [0,1] to values in the original space"""
        v = np.zeros(X.shape).tolist()

        for ii, param in enumerate(self.searchable_params):
            for jj, x in enumerate(X[:, ii]):
                v[jj][ii] = param.ppf(x)
        return v

    def convert_run_to_normalized_vector(self, run):
        """Converts run parameters to vectors with all values compressed to [0, 1]"""
        run_params = run.config or {}
        X = np.zeros([len(self.searchable_params)])

        # we ignore keys we haven't seen in our spec
        # we don't handle the case where a key is missing from run config
        for key, config_value in run_params.items():
            if key in self.param_names_to_index:
                param = self.param_names_to_param[key]
                bayes_opt_index = self.param_names_to_index[key]
                # if param.type == HyperParameter.CATEGORICAL:
                #    bayes_opt_value = param.value_to_int(config_value["value"])
                # else:
                bayes_opt_value = param.cdf(config_value["value"])

                X[bayes_opt_index] = bayes_opt_value
        return X


class EarlyTerminate():
    def _load_metric_name_and_goal(self, sweep_config):
        if not 'metric' in sweep_config:
            raise ValueError("Key 'metric' required for early termination")

        self.metric_name = sweep_config['metric']['name']

        self.maximize = False
        if 'goal' in sweep_config['metric']:
            if sweep_config['metric']['goal'] == 'maximize':
                self.maximize = True

    def _load_run_metric_history(self, run):
        metric_history = []
        for line in run.history:
            if self.metric_name in line:
                m = line[self.metric_name]
                metric_history.append(m)

        if self.maximize:
            metric_history = [-m for m in metric_history]

        return metric_history

    def stop_runs(sweep_config, runs):
        return []

class HyperbandEarlyTerminate(EarlyTerminate):
    """
    Implementation of the Hyperband algorithm from
      Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization
      https://arxiv.org/pdf/1603.06560.pdf

    Arguments
    bands - Array of iterations to potentially early terminate algorithms
    r - float in [0, 1] - fraction of runs to allow to pass through a band
        r=1 means let all runs through and r=0 means let no runs through
    """
    def __init__(self, bands, r):
        if len(bands) < 1:
            raise "Bands must be an array of length at least 1"
        if r < 0 or r > 1:
            raise "r must be a float between 0 and 1"

        self.bands = bands
        self.r = r

    @classmethod
    def init_from_max_iter(cls, max_iter, eta, s):
        band = max_iter
        bands = []
        for i in range(s):
            band /= eta
            if band < 1:
                break

            bands.append(int(band))

        return cls(sorted(bands), 1.0/eta)


    @classmethod
    def init_from_min_iter(cls, min_iter, eta):
        if eta <= 1:
            raise "eta must be greater than 1"
        if min_iter < 1:
            raise "min_iter must be at least 1"

        band = min_iter
        bands = []
        for i in range(100):
            bands.append(int(band))
            band *= eta

        return cls(bands, 1.0/eta)

    def stop_runs(self, sweep_config, runs):
        terminate_run_names = []
        self._load_metric_name_and_goal(sweep_config)

        all_run_histories = []  # we're going to look at every run
        for run in runs:
            #if run.state == "finished":  # complete run
            history = self._load_run_metric_history(run)
            if len(history) > 0:
                all_run_histories.append(history)

        self.thresholds = []
        # iterate over the histories at every band and find the threshold for a run to be in the top r percentile
        for band in self.bands:
            # values of metric at iteration number "band"
            band_values = [h[band] for h in all_run_histories if len(h) > band]

            if len(band_values) == 0:
                threshold = np.inf
            else:
                threshold = sorted(band_values)[int((self.r) * len(band_values))]

            self.thresholds.append(threshold)


        for run in runs:
            if run.state == "running":
                history = self._load_run_metric_history(run)

                closest_band = -1
                closest_threshold = 0
                for band, threshold in zip(self.bands, self.thresholds):
                    if band < len(history):
                        closest_band = band
                        closest_threshold = threshold
                    else:
                        break

                if closest_band == -1: # no bands apply yet
                    break
                else:
                    if min(history) > closest_threshold:
                        terminate_run_names.append(run.name)


        return terminate_run_names


class EnvelopeEarlyTerminate(EarlyTerminate):
    def __init__(self, fraction=0.3, min_runs=3, start_iter=3):
        self.fraction = fraction
        self.min_runs = min_runs
        self.start_iter = start_iter

    def stop_runs(self, sweep_config, runs):
        terminate_run_names = []
        self._load_metric_name_and_goal(sweep_config)

        complete_run_histories = []
        complete_run_metrics = []
        for run in runs:
            if run.state == "finished":  # complete run
                history = self._load_run_metric_history(run)
                if len(history) > 0:
                    complete_run_histories.append(history)
                    complete_run_metrics.append(min(history))

        complete_runs_count = len(complete_run_histories)
        if complete_runs_count < self.min_runs:
            return []

        n = max(int(np.ceil(complete_runs_count * self.fraction)), self.min_runs)

        envelope = early_terminate.envelope_from_top_n(
            complete_run_histories, complete_run_metrics, n)

        for run in runs:
            if run.state == "running":
                history = self._load_run_metric_history(run)

                if not early_terminate.is_inside_envelope(history, envelope,
                                                          ignore_first_n_iters=self.start_iter):
                    terminate_run_names.append(run.name)
        return terminate_run_names


class RandomSearch(Search):
    def next_run(self, sweep):
        #print(sweep)
        if 'parameters' not in sweep['config']:
            raise ValueError('Random search requires "parameters" section')
        config = sweep['config']['parameters']
        params = HyperParameterSet.from_config(config)

        for param in params:
            param.value = param.sample()

        return (params.to_config(), None)


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
                raise ValueError(f'Parameter {p.name} is a disallowed type with grid search. Grid search requires all parameters to be categorical or constant')

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
                #print(f"not same {run.config[key]} {value}")

                return False
        return True

    def _runs_contains_param_values(self, runs, params):
        ret_val = any(self._run_contains_param_values(run, params)
                      for run in runs)
        return any(self._run_contains_param_values(run, params) for run in runs)


class TimePredictor():
    def predict_time(self, sweep_config, runs, new_run):
        config = sweep_config['parameters']

        params = HyperParameterSet.from_config(config)

        X_bounds = params.numeric_bounds()

        X = []
        y = []

        for run in runs:
            if run.state == "finished":  # complete
                if '_runtime' in run.summaryMetrics:
                    X.append(params.convert_run_to_vector(run))
                    y.append(run.summaryMetrics['_runtime'])

        if len(X) <= 1:
            return None, None

        new_run_vector = params.convert_run_to_vector(new_run)

        mean, stddev = bayes.predict(X, y, new_run_vector)

        return mean, [max(0, mean - 2 * stddev), mean + 2 * stddev]


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
            max_metric = max([self._metric_from_run(sweep['config'], run) for run in runs
                              if run.state == "finished"])

        for run in runs:
            X_norm = params.convert_run_to_normalized_vector(run)
            if run.state == "finished":
                # run is complete
                metric = self._metric_from_run(sweep['config'], run)
                if math.isnan(metric):
                    metric = max_metric
                y.append(metric)
                sample_X.append(X_norm)
            elif run.state == "running":
                # run is in progress
                # we wont use the metric, but we should pass it into our optimizer to
                # account for the fact that it is running
                current_X.append(X_norm)
            elif run.state == "failed" or run.state == "crashed":
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
            prob_of_failure, expected_runtime) = bayes.next_sample(
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
