"""Hyperparameter search parameters."""

import random

from typing import List, Tuple, Dict, Any

import numpy as np
import scipy.stats as stats

import jsonschema

from .run import SweepRun
from .config import fill_parameter
from ._types import ArrayLike


class HyperParameter:

    CONSTANT = "param_single_value"
    CATEGORICAL = "param_categorical"
    INT_UNIFORM = "param_int_uniform"
    UNIFORM = "param_uniform"
    LOG_UNIFORM = "param_loguniform"
    Q_UNIFORM = "param_quniform"
    Q_LOG_UNIFORM = "param_qloguniform"
    NORMAL = "param_normal"
    Q_NORMAL = "param_qnormal"
    LOG_NORMAL = "param_lognormal"
    Q_LOG_NORMAL = "param_qlognormal"
    BETA = "param_beta"
    Q_BETA = "param_qbeta"

    def __init__(self, name: str, config: dict):
        """A hyperparameter to optimize.

        >>> parameter = HyperParameter('int_unif_distributed', {'min': 1, 'max': 10})
        >>> assert parameter.config['min'] == 1
        >>> parameter = HyperParameter('normally_distributed', {'distribution': 'normal'})
        >>> assert np.isclose(parameter.config['mu'], 0)

        Args:
            name: The name of the hyperparameter.
            config: Hyperparameter config dict.
        """

        self.name = name

        result = fill_parameter(config)
        if result is None:
            raise jsonschema.ValidationError(
                f"invalid hyperparameter configuration: {name}"
            )

        self.type, self.config = result
        if self.config is None or self.type is None:
            raise ValueError(
                "list of allowed schemas has length zero; please provide some valid schemas"
            )

        self.value = (
            None if self.type != HyperParameter.CONSTANT else self.config["value"]
        )

    def value_to_int(self, value: Any) -> int:
        """Get the index of the value of a categorically distributed HyperParameter.

        >>> parameter = HyperParameter('a', {'values': [1, 2, 3]})
        >>> assert parameter.value_to_int(2) == 1

        Args:
             value: The value to look up.

        Returns:
            The index of the value.
        """

        if self.type != HyperParameter.CATEGORICAL:
            raise ValueError("Can only call value_to_int on categorical variable")

        for ii, test_value in enumerate(self.config["values"]):
            if value == test_value:
                return ii

        raise ValueError(
            f"{value} is not a permitted value of the categorical hyperparameter {self.name} "
            f"in the current sweep."
        )

    def cdf(self, x: ArrayLike) -> ArrayLike:
        """Cumulative distribution function (CDF).

        In probability theory and statistics, the cumulative distribution function
        (CDF) of a real-valued random variable X, is the probability that X will
        take a value less than or equal to x.

        Args:
             x: Parameter values to calculate the CDF for. Can be scalar or 1-d.
        Returns:
            Probability that a random sample of this hyperparameter will be less than x.
        """
        if self.type == HyperParameter.CONSTANT:
            return np.zeros_like(x)
        elif self.type == HyperParameter.CATEGORICAL:
            # NOTE: Indices expected for categorical parameters, not values.
            return stats.randint.cdf(x, 0, len(self.config["values"]))
        elif self.type == HyperParameter.INT_UNIFORM:
            return stats.randint.cdf(x, self.config["min"], self.config["max"] + 1)
        elif (
            self.type == HyperParameter.UNIFORM or self.type == HyperParameter.Q_UNIFORM
        ):
            return stats.uniform.cdf(
                x, self.config["min"], self.config["max"] - self.config["min"]
            )
        elif (
            self.type == HyperParameter.LOG_UNIFORM
            or self.type == HyperParameter.Q_LOG_UNIFORM
        ):
            return stats.uniform.cdf(
                np.log(x), self.config["min"], self.config["max"] - self.config["min"]
            )
        elif self.type == HyperParameter.NORMAL or self.type == HyperParameter.Q_NORMAL:
            return stats.norm.cdf(x, loc=self.config["mu"], scale=self.config["sigma"])
        elif (
            self.type == HyperParameter.LOG_NORMAL
            or self.type == HyperParameter.Q_LOG_NORMAL
        ):
            return stats.lognorm.cdf(
                x, s=self.config["sigma"], scale=np.exp(self.config["mu"])
            )
        elif self.type == HyperParameter.BETA or self.type == HyperParameter.Q_BETA:
            return stats.beta.cdf(x, a=self.config["a"], b=self.config["b"])
        else:
            raise ValueError("Unsupported hyperparameter distribution type")

    def ppf(self, x: ArrayLike) -> Any:
        """Percentage point function (PPF).

        In probability theory and statistics, the percentage point function is
        the inverse of the CDF: it returns the value of a random variable at the
        xth percentile.

        Args:
             x: Percentiles of the random variable. Can be scalar or 1-d.
        Returns:
            Value of the random variable at the specified percentile.
        """
        if np.any((x < 0.0) | (x > 1.0)):
            raise ValueError("Can't call ppf on value outside of [0,1]")
        if self.type == HyperParameter.CONSTANT:
            return self.config["value"]
        elif self.type == HyperParameter.CATEGORICAL:
            retval = [
                self.config["values"][i]
                for i in np.atleast_1d(
                    stats.randint.ppf(x, 0, len(self.config["values"])).astype(int)
                ).tolist()
            ]
            if np.isscalar(x):
                return retval[0]
            return retval
        elif self.type == HyperParameter.INT_UNIFORM:
            return (
                stats.randint.ppf(x, self.config["min"], self.config["max"] + 1)
                .astype(int)
                .tolist()
            )
        elif self.type == HyperParameter.UNIFORM:
            return stats.uniform.ppf(
                x, self.config["min"], self.config["max"] - self.config["min"]
            )
        elif self.type == HyperParameter.Q_UNIFORM:
            r = stats.uniform.ppf(
                x, self.config["min"], self.config["max"] - self.config["min"]
            )
            ret_val = np.round(r / self.config["q"]) * self.config["q"]
            if isinstance(self.config["q"], int):
                return ret_val.astype(int)
            else:
                return ret_val
        elif self.type == HyperParameter.LOG_UNIFORM:
            return np.exp(
                stats.uniform.ppf(
                    x, self.config["min"], self.config["max"] - self.config["min"]
                )
            )
        elif self.type == HyperParameter.Q_LOG_UNIFORM:
            r = np.exp(
                stats.uniform.ppf(
                    x, self.config["min"], self.config["max"] - self.config["min"]
                )
            )
            ret_val = np.round(r / self.config["q"]) * self.config["q"]
            if isinstance(self.config["q"], int):
                return ret_val.astype(int)
            else:
                return ret_val
        elif self.type == HyperParameter.NORMAL:
            return stats.norm.ppf(x, loc=self.config["mu"], scale=self.config["sigma"])
        elif self.type == HyperParameter.Q_NORMAL:
            r = stats.norm.ppf(x, loc=self.config["mu"], scale=self.config["sigma"])
            ret_val = np.round(r / self.config["q"]) * self.config["q"]
            if isinstance(self.config["q"], int):
                return ret_val.astype(int)
            else:
                return ret_val
        elif self.type == HyperParameter.LOG_NORMAL:
            # https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.lognorm.html
            return stats.lognorm.ppf(
                x, s=self.config["sigma"], scale=np.exp(self.config["mu"])
            )
        elif self.type == HyperParameter.Q_LOG_NORMAL:
            r = stats.lognorm.ppf(
                x, s=self.config["sigma"], scale=np.exp(self.config["mu"])
            )
            ret_val = np.round(r / self.config["q"]) * self.config["q"]

            if isinstance(self.config["q"], int):
                return ret_val.astype(int)
            else:
                return ret_val

        elif self.type == HyperParameter.BETA:
            return stats.beta.ppf(x, a=self.config["a"], b=self.config["b"])
        elif self.type == HyperParameter.Q_BETA:
            r = stats.beta.ppf(x, a=self.config["a"], b=self.config["b"])
            ret_val = np.round(r / self.config["q"]) * self.config["q"]
            if isinstance(self.config["q"], int):
                return ret_val.astype(int)
            else:
                return ret_val
        else:
            raise ValueError("Unsupported hyperparameter distribution type")

    def sample(self) -> Any:
        """Randomly sample a value from the distribution of this HyperParameter."""
        return self.ppf(random.uniform(0.0, 1.0))

    def _to_config(self) -> Tuple[str, Dict]:
        config = dict(value=self.value)
        return self.name, config


class HyperParameterSet(list):
    def __init__(self, items: List[HyperParameter]):
        """A set of HyperParameters.

        >>> hp1 = HyperParameter('a', {'values': [1, 2, 3]})
        >>> hp2 = HyperParameter('b', {'distribution': 'normal'})
        >>> HyperParameterSet([hp1, hp2])

        Args:
            items: A list of HyperParameters to construct the set from.
        """

        for item in items:
            if not isinstance(item, HyperParameter):
                raise TypeError(
                    f"each item used to initialize HyperParameterSet must be a HyperParameter, got {item}"
                )

        super().__init__(items)
        self.searchable_params = [
            param for param in self if param.type != HyperParameter.CONSTANT
        ]

        self.param_names_to_index = {}
        self.param_names_to_param = {}

        for ii, param in enumerate(self.searchable_params):
            self.param_names_to_index[param.name] = ii
            self.param_names_to_param[param.name] = param

    @classmethod
    def from_config(cls, config: Dict):
        """Instantiate a HyperParameterSet based the parameters section of a SweepConfig.

        >>> sweep_config = {'method': 'grid', 'parameters': {'a': {'values': [1, 2, 3]}}}
        >>> hps = HyperParameterSet.from_config(sweep_config['parameters'])

        Args:
            config: The parameters section of a SweepConfig.
        """
        hpd = cls(
            [
                HyperParameter(param_name, param_config)
                for param_name, param_config in sorted(config.items())
            ]
        )
        return hpd

    def to_config(self) -> Dict:
        """Convert a HyperParameterSet to a SweepRun config."""
        return dict([param._to_config() for param in self])

    def convert_runs_to_normalized_vector(self, runs: List[SweepRun]) -> ArrayLike:
        """Converts a list of SweepRuns to an array of normalized parameter vectors.

        Args:
            runs: List of runs to convert.

        Returns:
            A 2d array of normalized parameter vectors.
        """

        runs_params = [run.config for run in runs]
        X = np.zeros([len(self.searchable_params), len(runs)])

        for key, bayes_opt_index in self.param_names_to_index.items():
            param = self.param_names_to_param[key]
            row = np.array(
                [
                    (
                        param.value_to_int(config[key]["value"])
                        if param.type == HyperParameter.CATEGORICAL
                        else config[key]["value"]
                    )
                    if key in config
                    # filter out incorrectly specified runs
                    else np.nan
                    for config in runs_params
                ]
            )

            X_row = param.cdf(row)
            # only use values where input wasn't nan
            non_nan = ~np.isnan(row)
            X[bayes_opt_index, non_nan] = X_row[non_nan]

        return np.transpose(X)
