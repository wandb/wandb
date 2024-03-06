import os
import platform
from pathlib import Path

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.artifacts.staging import get_staging_dir


def test_artifact(runner, user):
    # wandb artifact put
    with open("artifact.txt", "w") as f:
        f.write("My Artifact")
    result = runner.invoke(cli.artifact, ["put", "artifact.txt", "-n", "test/simple"])
    assert result.exit_code == 0
    assert "Uploading file artifact.txt to:" in result.output
    assert "test/simple:v0" in result.output

    # wandb artifact ls
    result = runner.invoke(cli.artifact, ["ls", "test"])
    assert result.exit_code == 0
    assert "11.0B" in result.output
    assert "simple:v0" in result.output

    # wandb artifact get
    result = runner.invoke(cli.artifact, ["get", "test/simple:v0"])
    assert result.exit_code == 0
    assert "Downloading dataset artifact" in result.output
    path = os.path.join(".", "artifacts", "simple:v0")
    if platform.system() == "Windows":
        head, tail = os.path.splitdrive(path)
        path = head + tail.replace(":", "-")
    assert "Artifact downloaded to %s" % os.path.abspath(path) in result.output
    assert os.path.exists(path)


@pytest.mark.wandb_core_failure(feature="artifacts_cache")
def test_artifact_put_with_cache_enabled(runner, user, monkeypatch, tmp_path, api):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path))
    staging_dir = Path(get_staging_dir())
    cache_dir = Path(tmp_path / "cache")
    monkeypatch.setenv("WANDB_CACHE_DIR", str(cache_dir))
    data_path = Path(tmp_path / "random.txt")

    with open(data_path, "w") as f:
        f.write("test 123")
    result = runner.invoke(cli.artifact, ["put", str(data_path), "-n", "test/simple"])
    assert result.exit_code == 0
    assert f"Uploading file {data_path} to:" in result.output
    assert "test/simple:v0" in result.output

    # The staged file is deleted after logging
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0

    # The file is cached
    artifact = api.artifact("test/simple:latest")
    manifest_entry = artifact.manifest.entries["random.txt"]
    wandb.termwarn(
        f"\n\ncache dirs: {artifact.manifest.storage_policy._cache._cache_dir}\n\n"
    )
    wandb.termwarn(f"\n\\manifest entry: {artifact.manifest.entries}\n\n")
    _, found, _ = artifact.manifest.storage_policy._cache.check_md5_obj_path(
        manifest_entry.digest, manifest_entry.size
    )
    assert found


def test_artifact_put_with_cache_disabled(runner, user, monkeypatch, tmp_path, api):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path))
    staging_dir = Path(get_staging_dir())
    cache_dir = Path(tmp_path / "cache")
    monkeypatch.setenv("WANDB_CACHE_DIR", str(cache_dir))
    data_path = Path(tmp_path / "random.txt")

    with open(data_path, "w") as f:
        f.write("test 123")
    result = runner.invoke(
        cli.artifact, ["put", str(data_path), "-n", "test/simple", "--skip_cache"]
    )
    assert result.exit_code == 0
    assert f"Uploading file {data_path} to:" in result.output
    assert "test/simple:v0" in result.output

    # The staged file is deleted after logging
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0

    # The file is not cached
    artifact = api.artifact("test/simple:latest")
    manifest_entry = artifact.manifest.entries["random.txt"]
    _, found, _ = artifact.manifest.storage_policy._cache.check_md5_obj_path(
        manifest_entry.digest, manifest_entry.size
    )
    assert not found
