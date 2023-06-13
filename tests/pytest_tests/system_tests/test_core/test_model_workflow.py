import pytest


def test_offline_link_artifact(wandb_init):
    run = wandb_init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(None, "entity/project/portfolio", "latest")
    run.finish()
