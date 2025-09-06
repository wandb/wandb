import pytest
import wandb

from ..user_config import UserConfig


@pytest.fixture
def user_cfg() -> UserConfig:
    """Override the default user_cfg fixure to enable Runs V2.

    Only affects the test users created when running tests from this file.
    """
    return UserConfig(enable_runs_v2=True)


@pytest.mark.wandb_core_only
def test_fork(wandb_backend_spy):
    n_steps = 10
    fork_step = 5

    with wandb.init() as original_run:
        for i in range(n_steps):
            original_run.log({"metric": i})

    # import os
    # print(os.getcwd())

    with wandb.init(fork_from=f"{original_run.id}?_step={fork_step}") as fork_run:
        for i in range(n_steps):
            fork_run.log({"metric": i**2, "shmetric": -i})
