from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from wandb import env
from wandb.sdk.artifacts.artifact_file_cache import (
    ArtifactFileCache,
    get_artifact_file_cache,
)


@pytest.fixture
def artifact_file_cache(mocker: MockerFixture, tmp_path: Path) -> ArtifactFileCache:
    # Patch the environment variable controlling the cache directory for tests will need it (directly and indirectly)
    tmp_cache_dir = tmp_path.resolve() / "cache"
    mocker.patch.dict(os.environ, {env.CACHE_DIR: str(tmp_cache_dir)})
    return get_artifact_file_cache()
