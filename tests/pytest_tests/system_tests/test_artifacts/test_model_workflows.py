import pathlib
from typing import Callable

import pytest
from wandb import env
from wandb.sdk.wandb_run import Run


class FakeArtifact:
    def is_draft(self):
        return False


def test_offline_link_artifact(wandb_init):
    run = wandb_init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(FakeArtifact(), "entity/project/portfolio", "latest")
    run.finish()


def test_log_model(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.log_model(local_path, "test-model")
    run.finish()

    run = wandb_init()
    download_path = run.use_model("test-model:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
    run.finish()


def test_use_model(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test-model", type="model")
    logged_artifact.wait()
    download_path = run.use_model("test-model:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
    run.finish()


def test_use_model_error_artifact_type(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test-model", type="dataset")
    logged_artifact.wait()
    with pytest.raises(AssertionError):
        _ = run.use_model("test-model:v0")
    run.finish()


def test_link_model(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()

    run = wandb_init()
    download_path = run.use_model("model-registry/test_portfolio:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test_model:v0/boom.txt"
    run.finish()


def test_link_model_error_artifact_type(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test_model", type="dataset")
    logged_artifact.wait()
    with pytest.raises(AssertionError):
        run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()


def test_link_model_log_new_artifact(
    wandb_init: Callable[..., Run],
    tmp_path: pathlib.Path,
):
    run = wandb_init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()

    run = wandb_init()
    download_path = run.use_model("model-registry/test_portfolio:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test_model:v0/boom.txt"
    run.finish()
