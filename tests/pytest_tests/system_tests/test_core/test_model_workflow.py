import pytest


class FakeArtifact:
    def is_draft(self):
        return False


def test_offline_link_artifact(wandb_init):
    run = wandb_init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(FakeArtifact(), "entity/project/portfolio", "latest")
    run.finish()
