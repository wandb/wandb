import os

from wandb import wandb_sdk


def test_artifacts_cache_cleanup(runner):
    with runner.isolated_filesystem():
        os.mkdir("cache")
        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
        reclaimed_bytes = cache.cleanup(0)
        assert reclaimed_bytes == 0
