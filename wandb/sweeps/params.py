"""
Hyperparameter search parameters
"""

import random
import numpy as np
from wandb.util import get_module
#import scipy.stats as stats


stats = get_module('scipy.stats')


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
            raise ValueError("Need to specify {} \
                with distribution: {}.".format(param_name, param_config['distribution']))

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
                    "Unexpected hyperparameter configuration {}".format(key))

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
                    "Unsupported distribution: {}".format(self.distribution))

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
        config = {}
        if self.value != None:
            config['value'] = self.value
            # Remove values list if we have picked a value for this parameter
            self.config.pop('values', None)
        return self.name, config

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
                    "Need to have a max with a min or specify the distribution for parameter {}".format(param_name))
            self.min = config['min']
            self.max = config['max']

            if type(config['min']) == int and type(config['max']) == int:
                self.type = HyperParameter.INT_UNIFORM
            elif type(config['min']) in (int, float) and type(config['max']) in (int, float):
                self.type = HyperParameter.UNIFORM
            else:
                raise ValueError(
                    "Min and max must be type int or float for parameter {}".format(param_name))

        elif 'value' in config:
            self.type = HyperParameter.CONSTANT
            self.value = config['value']
        else:
            raise ValueError("Bad configuration for parameter: {}".format(param_name))


class HyperParameterSet(list):
    @staticmethod
    def from_config(config):
        hpd = HyperParameterSet([HyperParameter(param_name, param_config)
                                 for param_name, param_config in sorted(config.items())])
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
