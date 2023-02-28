from pytest import fixture
from wandb import wandb_sdk


@fixture
def cache(tmp_path):
    return wandb_sdk.wandb_artifacts.ArtifactsCache(tmp_path)
