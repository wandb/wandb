import itertools
import random
import hashlib
import yaml
from typing import Any, List, Optional, Union

from .config.cfg import SweepConfig
from .run import SweepRun
from .params import HyperParameter, HyperParameterSet


def yaml_hash(value: Any) -> str:
    return hashlib.md5(
        yaml.dump(value, default_flow_style=True, sort_keys=True).encode("ascii")
    ).hexdigest()


def grid_search_next_runs(
    runs: List[SweepRun],
    sweep_config: Union[dict, SweepConfig],
    validate: bool = False,
    n: int = 1,
    randomize_order: bool = False,
) -> List[Optional[SweepRun]]:
    """Suggest runs with Hyperparameters drawn from a grid.

    >>> suggestion = grid_search_next_runs([], {'method': 'grid', 'parameters': {'a': {'values': [1, 2, 3]}}})
    >>> assert suggestion[0].config['a']['value'] == 1

    Args:
        runs: The runs in the sweep.
        sweep_config: The sweep's config.
        randomize_order: Whether to randomize the order of the grid search.
        n: The number of runs to draw
        validate: Whether to validate `sweep_config` against the SweepConfig JSONschema.
           If true, will raise a Validation error if `sweep_config` does not conform to
           the schema. If false, will attempt to run the sweep with an unvalidated schema.

    Returns:
        The suggested runs.
    """

    # make sure the sweep config is valid
    if validate:
        sweep_config = SweepConfig(sweep_config)

    if sweep_config["method"] != "grid":
        raise ValueError("Invalid sweep configuration for grid_search_next_run.")

    if "parameters" not in sweep_config:
        raise ValueError('Grid search requires "parameters" section')
    params = HyperParameterSet.from_config(sweep_config["parameters"])

    # Check that all parameters are categorical or constant
    for p in params:
        if p.type != HyperParameter.CATEGORICAL and p.type != HyperParameter.CONSTANT:
            raise ValueError(
                "Parameter %s is a disallowed type with grid search. Grid search requires all parameters to be categorical or constant"
                % p.name
            )

    # we can only deal with discrete params in a grid search
    discrete_params = HyperParameterSet(
        [p for p in params if p.type == HyperParameter.CATEGORICAL]
    )

    # build an iterator over all combinations of param values
    param_names = [p.name for p in discrete_params]
    param_values = [p.config["values"] for p in discrete_params]
    param_hashes = [
        [yaml_hash(value) for value in p.config["values"]] for p in discrete_params
    ]
    value_hash_lookup = {
        name: dict(zip(hashes, vals))
        for name, vals, hashes in zip(param_names, param_values, param_hashes)
    }

    all_param_hashes = list(itertools.product(*param_hashes))
    if randomize_order:
        random.shuffle(all_param_hashes)

    param_hashes_seen = set(
        [
            tuple(
                yaml_hash(run.config[name]["value"])
                for name in param_names
                if name in run.config
            )
            for run in runs
        ]
    )

    hash_gen = (
        hash_val for hash_val in all_param_hashes if hash_val not in param_hashes_seen
    )

    retval: List[Optional[SweepRun]] = []
    for _ in range(n):

        # this is O(1)
        next_hash = next(hash_gen, None)

        # we have searched over the entire parameter space
        if next_hash is None:
            retval.append(None)
            return retval

        for param, hash_val in zip(discrete_params, next_hash):
            param.value = value_hash_lookup[param.name][hash_val]

        run = SweepRun(config=params.to_config())
        retval.append(run)

        param_hashes_seen.add(next_hash)

    return retval
