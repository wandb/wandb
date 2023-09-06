import pytest
import wandb
from wandb import Api

from .test_wandb_sweep import (
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
    SWEEP_CONFIG_RANDOM,
    VALID_SWEEP_CONFIGS_MINIMAL,
)


@pytest.mark.parametrize(
    "sweep_config,expected_run_count",
    [
        (SWEEP_CONFIG_GRID, 3),
        (SWEEP_CONFIG_GRID_NESTED, 9),
        (SWEEP_CONFIG_BAYES, None),
        (SWEEP_CONFIG_RANDOM, None),
    ],
    ids=["test grid", "test grid nested", "test bayes", "test random"],
)
def test_sweep_api_expected_run_count(
    user, relay_server, sweep_config, expected_run_count
):
    _project = "test"
    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        print(q)

    print(f"sweep_id{sweep_id}")
    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")

    assert sweep.expected_run_count == expected_run_count


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_api(user, relay_server, sweep_config):
    _project = "test"
    with relay_server():
        sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    print(f"sweep_id{sweep_id}")
    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")
    assert sweep.entity == user
    assert f"{user}/{_project}/sweeps/{sweep_id}" in sweep.url
    assert sweep.state == "PENDING"
    assert str(sweep) == f"<Sweep {user}/test/{sweep_id} (PENDING)>"
