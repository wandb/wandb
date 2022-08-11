"""Sweep tests."""
from typing import Any, Dict

import pytest
import wandb

from .assets.sweep_configs import get_valid_sweep_configs, get_invalid_sweep_configs

@pytest.mark.parametrize("sweep_config", get_valid_sweep_configs())
def test_sweep_create(relay_server, sweep_config):
    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_config)
    assert sweep_id in relay.context.entries


@pytest.mark.parametrize("sweep_config", get_valid_sweep_configs())
def test_sweep_entity_project_callable(user, relay_server, sweep_config):
    def sweep_callable():
        return sweep_config

    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_callable, project="test", entity=user)
    sweep_response = relay.context.entries[sweep_id]
    assert sweep_response["project"]["entity"]["name"] == user
    assert sweep_response["project"]["name"] == "test"
    assert sweep_response["name"] == sweep_id


def test_minmax_validation():
    api = wandb.apis.InternalApi()
    sweep_config = {
        "name": "My Sweep",
        "method": "random",
        "parameters": {"parameter1": {"min": 0, "max": 1}},
    }

    filled = api.api._validate_config_and_fill_distribution(sweep_config)
    assert "distribution" in filled["parameters"]["parameter1"]
    assert "int_uniform" == filled["parameters"]["parameter1"]["distribution"]

    sweep_config = {
        "name": "My Sweep",
        "method": "random",
        "parameters": {"parameter1": {"min": 0.0, "max": 1.0}},
    }

    filled = api.api._validate_config_and_fill_distribution(sweep_config)
    assert "distribution" in filled["parameters"]["parameter1"]
    assert "uniform" == filled["parameters"]["parameter1"]["distribution"]

    sweep_config = {
        "name": "My Sweep",
        "method": "random",
        "parameters": {"parameter1": {"min": 0.0, "max": 1}},
    }

    with pytest.raises(ValueError):
        api.api._validate_config_and_fill_distribution(sweep_config)
