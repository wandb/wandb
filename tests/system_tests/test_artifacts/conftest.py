from __future__ import annotations

from pathlib import Path

import wandb
from pytest import MonkeyPatch, fixture
from wandb import Api, Artifact, env
from wandb.sdk.artifacts.staging import get_staging_dir


@fixture
def logged_artifact(user: str, example_files, api: Api) -> Artifact:
    with wandb.init(entity=user, project="project") as run:
        artifact = Artifact("test-artifact", "dataset")
        artifact.add_dir(example_files)
        run.log_artifact(artifact)
    artifact.wait()
    return api.artifact(f"{user}/project/test-artifact:v0")


@fixture
def linked_artifact(user: str, logged_artifact: Artifact, api: Api) -> Artifact:
    with wandb.init(entity=user, project="other-project") as run:
        run.link_artifact(logged_artifact, "linked-from-portfolio")

    return api.artifact(f"{user}/other-project/linked-from-portfolio:v0")


# ------------------------------------------------------------------------------
# Fixtures that override "global" default paths via environment variables
@fixture
def override_env_dirs(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """When requested, overrides the cache, staging, and artifact directories via environment variables."""
    monkeypatch.setenv(env.CACHE_DIR, str(tmp_path / "my-cache"))
    monkeypatch.setenv(env.DATA_DIR, str(tmp_path / "my-staging"))
    monkeypatch.setenv(env.ARTIFACT_DIR, str(tmp_path / "my-artifacts"))


@fixture
def temp_cache_dir(override_env_dirs: None) -> Path:
    """When requested, overrides the cache directory and returns it."""
    return Path(env.get_cache_dir())


@fixture
def temp_staging_dir(override_env_dirs: None) -> Path:
    """When requested, overrides the staging directory and returns it."""
    return Path(get_staging_dir())


@fixture
def temp_artifact_dir(override_env_dirs: None) -> Path:
    """When requested, overrides the artifact directory via `WANDB_ARTIFACT_DIR` and returns it."""
    return Path(env.get_artifact_dir())
