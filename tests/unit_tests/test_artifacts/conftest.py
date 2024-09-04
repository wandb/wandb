from pathlib import Path

import pytest
from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


@pytest.fixture
def artifact_file_cache(tmp_path: Path) -> ArtifactFileCache:
    return ArtifactFileCache(tmp_path / "artifacts-cache")
