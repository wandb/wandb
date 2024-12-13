import pathlib

import pytest
import wandb
from wandb import env


class FakeArtifact:
    def wait(self):
        pass

    def is_draft(self):
        return False


def test_offline_link_artifact(user):
    run = wandb.init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(FakeArtifact(), "entity/project/portfolio", "latest")
    run.finish()


def test_log_model(
    tmp_path: pathlib.Path,
    user,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.log_model(local_path, "test-model")
    run.finish()

    run = wandb.init()
    download_path = run.use_model("test-model:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
    run.finish()


def test_use_model(
    tmp_path: pathlib.Path,
    user,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test-model", type="model")
    logged_artifact.wait()
    download_path = run.use_model("test-model:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test-model:v0/boom.txt"
    run.finish()


def test_use_model_error_artifact_type(
    user,
    tmp_path: pathlib.Path,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test-model", type="dataset")
    logged_artifact.wait()
    with pytest.raises(AssertionError):
        _ = run.use_model("test-model:v0")
    run.finish()


def test_link_model(
    user,
    tmp_path: pathlib.Path,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()

    run = wandb.init()
    download_path = run.use_model("model-registry/test_portfolio:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test_model:v0/boom.txt"
    run.finish()


def test_link_model_error_artifact_type(
    user,
    tmp_path: pathlib.Path,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")

    logged_artifact = run.log_artifact(local_path, name="test_model", type="dataset")
    logged_artifact.wait()
    with pytest.raises(AssertionError):
        run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()


def test_link_model_log_new_artifact(
    user,
    tmp_path: pathlib.Path,
):
    run = wandb.init()
    local_path = tmp_path / "boom.txt"
    local_path.write_text("testing")
    run.link_model(local_path, "test_portfolio", "test_model")
    run.finish()

    run = wandb.init()
    download_path = run.use_model("model-registry/test_portfolio:v0")
    file = download_path
    assert file == f"{env.get_artifact_dir()}/test_model:v0/boom.txt"
    run.finish()
