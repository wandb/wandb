from pathlib import Path

import pytest
from wandb.sdk.artifacts.artifacts_cache import ArtifactsCache


@pytest.fixture
def artifacts_cache(tmp_path: Path) -> ArtifactsCache:
    return ArtifactsCache(tmp_path / "artifacts-cache")
