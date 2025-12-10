from __future__ import annotations

import os
import platform
from pathlib import Path

from pytest import mark
from wandb.cli import cli
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.lib.filesystem import mkdir_exists_ok


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
    assert f"Artifact downloaded to {os.path.abspath(path)}" in result.output
    assert os.path.exists(path)


@mark.usefixtures("override_env_dirs")
def test_artifact_put_with_cache_enabled(runner, user, tmp_path, api, temp_staging_dir):
    cache = get_artifact_file_cache()

    data_dir_path = Path(tmp_path / "data")
    data_path = Path(data_dir_path / "random.txt")
    try:
        mkdir_exists_ok(data_dir_path)
    except OSError:
        pass
    with open(data_path, "w") as f:
        f.write("test 123")
    result = runner.invoke(cli.artifact, ["put", str(data_path), "-n", "test/simple"])
    assert result.exit_code == 0
    assert f"Uploading file {data_path} to:" in result.output
    assert "test/simple:v0" in result.output

    # The staged file is deleted after logging
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0

    # The file is cached
    artifact = api.artifact("test/simple:latest")
    manifest_entry = artifact.manifest.entries["random.txt"]
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert found


@mark.usefixtures("override_env_dirs")
def test_artifact_put_with_cache_disabled(
    runner, user, tmp_path, api, temp_staging_dir
):
    cache = get_artifact_file_cache()

    data_dir_path = Path(tmp_path / "data")
    data_path = Path(data_dir_path / "random.txt")
    try:
        mkdir_exists_ok(data_dir_path)
    except OSError:
        pass
    with open(data_path, "w") as f:
        f.write("test 123")
    result = runner.invoke(
        cli.artifact, ["put", str(data_dir_path), "-n", "test/simple", "--skip_cache"]
    )
    assert result.exit_code == 0
    assert f"Uploading directory {data_dir_path} to:" in result.output
    assert "test/simple:v0" in result.output

    # The staged file is deleted after logging
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0

    # The file is not cached
    artifact = api.artifact("test/simple:latest")
    manifest_entry = artifact.manifest.entries["random.txt"]
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert not found
