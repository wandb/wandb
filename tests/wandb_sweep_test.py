"""Sweep tests"""
import os

import pytest
import wandb


def test_create_sweep(live_mock_server, test_settings):
    live_mock_server.set_ctx({"resume": True})
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }
    sweep_id = wandb.sweep(sweep_config)
    assert sweep_id == "test"


def test_sweep_entity_project_callable(live_mock_server, test_settings):
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {"parameter1": {"values": [1, 2, 3]}},
    }

    sweep_callable = lambda: sweep_config

    sweep_id = wandb.sweep(sweep_callable, project="test", entity="test")

    assert os.environ["WANDB_ENTITY"] == "test"
    assert os.environ["WANDB_PROJECT"] == "test"
    assert sweep_id == "test"


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
