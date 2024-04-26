"""Sweep tests."""

import json
import sys
from typing import Any, Dict, List

import pytest
import wandb
import wandb.apis
from wandb.cli import cli

# Sweep configs used for testing
SWEEP_CONFIG_GRID: Dict[str, Any] = {
    "name": "mock-sweep-grid",
    "method": "grid",
    "parameters": {"param1": {"values": [1, 2, 3]}},
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
    "parameters": {"param1": {"values": [1, 2, 3]}},
}
SWEEP_CONFIG_GRID_NESTED: Dict[str, Any] = {
    "name": "mock-sweep-grid",
    "method": "grid",
    "parameters": {
        "param1": {"values": [1, 2, 3]},
        "param2": {
            "parameters": {
                "param3": {"values": [1, 2, 3]},
                "param4": {"value": 1},
            }
        },
    },
}
SWEEP_CONFIG_BAYES: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "command": ["echo", "hello world"],
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
    "parameters": {"param1": {"values": [1, 2, 3]}},
}
SWEEP_CONFIG_BAYES_PROBABILITIES: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
    "parameters": {
        "param1": {"values": [1, 2, 3]},
        "param2": {"values": [1, 2, 3], "probabilities": [0.1, 0.2, 0.1]},
    },
}
SWEEP_CONFIG_BAYES_DISTRIBUTION: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
    "parameters": {
        "param1": {"distribution": "normal", "mu": 100, "sigma": 10},
    },
}
SWEEP_CONFIG_BAYES_DISTRIBUTION_NESTED: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
    "parameters": {
        "param1": {"values": [1, 2, 3]},
        "param2": {
            "parameters": {
                "param3": {"distribution": "q_uniform", "min": 0, "max": 256, "q": 1}
            },
        },
    },
}
SWEEP_CONFIG_BAYES_TARGET: Dict[str, Any] = {
    "name": "mock-sweep-bayes",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize", "target": 0.99},
    "parameters": {
        "param1": {"distribution": "normal", "mu": 100, "sigma": 10},
    },
}
SWEEP_CONFIG_RANDOM: Dict[str, Any] = {
    "name": "mock-sweep-random",
    "method": "random",
    "parameters": {"param1": {"values": [1, 2, 3]}},
}
SWEEP_CONFIG_BAYES_NONES: Dict[str, Any] = {
    "name": "mock-sweep-bayes-with-none",
    "method": "bayes",
    "metric": {"name": "metric1", "goal": "maximize"},
    "parameters": {"param1": {"values": [None, 1, 2, 3]}, "param2": {"value": None}},
}

# Minimal list of valid sweep configs
VALID_SWEEP_CONFIGS_MINIMAL: List[Dict[str, Any]] = [
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_RANDOM,
    SWEEP_CONFIG_GRID_HYPERBAND,
    SWEEP_CONFIG_GRID_NESTED,
]
# All valid sweep configs, be careful as this will slow down tests
VALID_SWEEP_CONFIGS_ALL: List[Dict[str, Any]] = [
    SWEEP_CONFIG_RANDOM,
    SWEEP_CONFIG_BAYES,
    # TODO: Probabilities seem to error out?
    # SWEEP_CONFIG_BAYES_PROBABILITIES,
    SWEEP_CONFIG_BAYES_DISTRIBUTION,
    SWEEP_CONFIG_BAYES_DISTRIBUTION_NESTED,
    SWEEP_CONFIG_BAYES_TARGET,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
    SWEEP_CONFIG_GRID_HYPERBAND,
]


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_ALL)
def test_sweep_create(user, relay_server, sweep_config):
    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_config, entity=user)
    assert sweep_id in relay.context.entries


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_entity_project_callable(user, relay_server, sweep_config):
    def sweep_callable():
        return sweep_config

    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_callable, project="test", entity=user)
    sweep_response = relay.context.entries[sweep_id]
    assert sweep_response["project"]["entity"]["name"] == user
    assert sweep_response["project"]["name"] == "test"
    assert sweep_response["name"] == sweep_id


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_ALL)
def test_object_dict_config(user, relay_server, sweep_config):
    class DictLikeObject(dict):
        def __init__(self, d: dict):
            super().__init__(d)

    with relay_server() as relay:
        sweep_id = wandb.sweep(DictLikeObject(sweep_config), entity=user)
    assert sweep_id in relay.context.entries


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


def test_add_run_to_existing_sweep(user, wandb_init, relay_server):
    # Test that updating settings with sweep_id includes it in upsertBucket mutation

    with relay_server() as relay:
        sweep_id = wandb.sweep(SWEEP_CONFIG_GRID, entity=user)
        settings = wandb.Settings()
        settings.update({"sweep_id": sweep_id})
        run = wandb_init(entity=user, settings=settings)
        run.log({"x": 1})
        run.finish()

    run_attrs = relay.context.get_run_attrs(run.id)
    assert sweep_id == run_attrs.sweep_name


def test_nones_validation():
    api = wandb.apis.InternalApi()
    filled = api.api._validate_config_and_fill_distribution(SWEEP_CONFIG_BAYES_NONES)
    assert filled["parameters"]["param1"]["values"] == [None, 1, 2, 3]
    assert filled["parameters"]["param2"]["value"] is None


@pytest.mark.parametrize("stop_method", ["cancel", "stop"])
def test_sweep_pause(runner, user, mocker, stop_method, monkeypatch):
    with runner.isolated_filesystem():
        # hack: need to reset the cling between reqs
        cli._get_cling_api(reset=True)
        sweep_config = {
            "name": f"My Sweep-{stop_method}",
            "method": "grid",
            "entity": user,
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config, entity=user, project=stop_method)

        def mock_read_from_queue(a, b, c):
            sys.exit(1)

        mocker.patch("wandb.wandb_agent.Agent._process_command", mock_read_from_queue)
        res_agent = runner.invoke(cli.agent, [sweep_id, "--project", stop_method])
        assert res_agent.exit_code == 1
        assert runner.invoke(cli.sweep, ["--pause", sweep_id]).exit_code == 0
        assert (
            runner.invoke(
                cli.sweep, ["--resume", sweep_id, "--project", stop_method]
            ).exit_code
            == 0
        )
        if stop_method == "stop":
            assert (
                runner.invoke(
                    cli.sweep, ["--stop", sweep_id, "--project", stop_method]
                ).exit_code
                == 0
            )
        else:
            assert (
                runner.invoke(
                    cli.sweep, ["--cancel", sweep_id, "--project", stop_method]
                ).exit_code
                == 0
            )


def test_sweep_scheduler(runner, user):
    cli._get_cling_api(reset=True)
    with runner.isolated_filesystem():
        with open("config.json", "w") as f:
            json.dump(
                {
                    "queue": "default",
                    "resource": "local-process",
                    "job": "mock-launch-job",
                    "scheduler": {
                        "resource": "local-process",
                    },
                },
                f,
            )
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        sweep_id = wandb.sweep(sweep_config)
        res = runner.invoke(
            cli.launch_sweep,
            ["config.json", "--resume_id", sweep_id],
        )
        print(res.output)
        assert res.exit_code == 0
