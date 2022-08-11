"""Sample Sweep Configurations.

Use convenience functions to get a list of valid and invalid sweep configurations:

> get_valid_sweep_configs()
> get_invalid_sweep_configs()

"""
import functools
from typing import Any, Dict, List


# Sweep configs used for testing
SWEEP_CONFIG_GRID: Dict[str, Any] = {
    "name": "mock-sweep-grid",
    "method": "grid",
}
SWEEP_CONFIG_GRID_HYPERBAND: Dict[str, Any] = {
    "name": "mock-sweep-grid-hyperband",
    "method": "grid",
    "early_terminate": {
        "type": "hyperband",
        "max_iter": 27,
        "s": 2,
        "eta": 3,
    },
    "metric": {"name": "metric1", "goal": "maximize"},
}
SWEEP_CONFIG_BAYES: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
}
SWEEP_CONFIG_RANDOM: Dict[str, Any] = {
    "name": "mock-sweep-random",
    "method": "random",
}

# List of all valid base configurations
VALID_BASE_CONFIGS: List[Dict[str, Any]] = [
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_HYPERBAND,
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_RANDOM,
]

# Valid parameter configurations
VALID_PARAM_VALUE: Dict[str, Any] = {"param1": {"value": 1}},
VALID_PARAM_VALUE_NESTED: Dict[str, Any] = {"param1": {"value": 1}},
VALID_PARAM_VALUES: Dict[str, Any] = {"param2": {"values": [1, 2, 3]}},
VALID_PARAM_VALUES_NESTED: Dict[str, Any] = {"param2": {"values": [1, 2, 3]}},

# All valid parameter configurations
VALID_PARAM_CONFIGS: List[Dict[str, Any]] = [
    VALID_PARAM_VALUE,
    VALID_PARAM_VALUE_NESTED,
    VALID_PARAM_VALUES,
    VALID_PARAM_VALUES_NESTED,
]

@functools.lru_cache
def get_valid_sweep_configs() -> List[Dict[str, Any]]:
    valid_sweep_configs: List[Dict[str, Any]] = []
    for base_config in VALID_BASE_CONFIGS:
        for param_config in VALID_PARAM_CONFIGS:
            config = {**base_config, **param_config}
            valid_sweep_configs.append(config)
    return valid_sweep_configs

@functools.lru_cache
def get_invalid_sweep_configs() -> List[Dict[str, Any]]:
    pass