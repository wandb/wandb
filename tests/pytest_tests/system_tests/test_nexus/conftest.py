import pytest
import wandb


@pytest.fixture(scope="session", autouse=True)
def wandb_require_nexus():
    wandb.require(experiment="nexus")
