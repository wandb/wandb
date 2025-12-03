from __future__ import annotations

import os
from pathlib import Path

import wandb
from pytest import fixture
from pytest_mock import MockerFixture
from wandb import Api, env
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.staging import get_staging_dir


@fixture
def logged_artifact(user: str, example_files, api: Api) -> Artifact:
    with wandb.init(entity=user, project="project") as run:
        artifact = wandb.Artifact("test-artifact", "dataset")
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
def override_env_cache_dir(mocker: MockerFixture, tmp_path: Path) -> None:
    """When requested, overrides the cache directory via `WANDB_CACHE_DIR`."""
    mocker.patch.dict(os.environ, {env.CACHE_DIR: str(tmp_path / "my-cache")})


@fixture
def override_env_staging_dir(mocker: MockerFixture, tmp_path: Path) -> None:
    """When requested, overrides the staging directory via `WANDB_DATA_DIR`."""
    mocker.patch.dict(os.environ, {env.DATA_DIR: str(tmp_path / "my-staging")})


@fixture
def override_env_artifact_dir(mocker: MockerFixture, tmp_path: Path) -> None:
    """When requested, overrides the artifact directory via `WANDB_ARTIFACT_DIR`."""
    mocker.patch.dict(os.environ, {env.ARTIFACT_DIR: str(tmp_path / "my-artifacts")})


@fixture
def cache_dir() -> Path:
    return env.get_cache_dir()


@fixture
def staging_dir() -> Path:
    return Path(get_staging_dir())


@fixture
def artifact_dir() -> Path:
    return Path(env.get_artifact_dir())
