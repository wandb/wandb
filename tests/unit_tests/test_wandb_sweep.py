"""Sweep tests"""

import pytest
import wandb


def test_create_sweep(user, relay_server):
    with relay_server() as relay:
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)

    assert sweep_id in relay.context.entries


def test_sweep_entity_project_callable(user, relay_server):
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }

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
