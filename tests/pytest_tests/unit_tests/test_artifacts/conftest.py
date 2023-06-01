from pytest import fixture
from wandb.sdk.artifacts.artifacts_cache import ArtifactsCache


@fixture
def cache(tmp_path):
    return ArtifactsCache(tmp_path)
