from __future__ import annotations

import os
import platform
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import responses
import wandb
from pytest import MonkeyPatch, mark, raises
from pytest_mock import MockerFixture
from wandb import Api, Artifact
from wandb.errors import CommError
from wandb.sdk.artifacts._internal_artifact import InternalArtifact
from wandb.sdk.artifacts._validators import NAME_MAXLEN, RESERVED_ARTIFACT_TYPE_PREFIX
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError, WaitTimeoutError
from wandb.sdk.lib.hashutil import md5_string

pytestmark = [
    # requesting the `user` fixture sets API env var for ALL tests in this module
    mark.usefixtures("user"),
]


def test_add_table_from_dataframe():
    import pandas as pd

    df_float = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float64)
    df_float32 = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float32)
    df_bool = pd.DataFrame([[True, False, True]], dtype=np.bool_)

    current_time = datetime.now()
    df_timestamp = pd.DataFrame(
        [[current_time + timedelta(days=i)] for i in range(10)], columns=["date"]
    )

    wb_table_float = wandb.Table(dataframe=df_float)
    wb_table_float32 = wandb.Table(dataframe=df_float32)
    wb_table_float32_recast = wandb.Table(dataframe=df_float32.astype(np.float64))
    wb_table_bool = wandb.Table(dataframe=df_bool)
    wb_table_timestamp = wandb.Table(dataframe=df_timestamp)

    with wandb.init() as run:
        artifact = Artifact("table-example", "dataset")
        artifact.add(wb_table_float, "wb_table_float")
        artifact.add(wb_table_float32_recast, "wb_table_float32_recast")
        artifact.add(wb_table_float32, "wb_table_float32")
        artifact.add(wb_table_bool, "wb_table_bool")

        # check that timestamp is correctly converted to ms and not ns
        json_repr = wb_table_timestamp.to_json(artifact)
        assert "data" in json_repr and np.isclose(
            json_repr["data"][0][0],
            current_time.replace(tzinfo=timezone.utc).timestamp() * 1000,
        )
        artifact.add(wb_table_timestamp, "wb_table_timestamp")

        run.log_artifact(artifact)


def test_artifact_error_for_invalid_aliases():
    with wandb.init() as run:
        artifact = Artifact("test-artifact", "dataset")
        error_aliases = [["latest", "workflow:boom"], ["workflow/boom/test"]]
        for aliases in error_aliases:
            with raises(ValueError) as e_info:
                run.log_artifact(artifact, aliases=aliases)
            assert (
                str(e_info.value)
                == "Aliases must not contain any of the following characters: '/', ':'"
            )

        for aliases in [["latest", "boom_test-q"]]:
            run.log_artifact(artifact, aliases=aliases)


@mark.parametrize(
    "invalid_name",
    (
        "a" * (NAME_MAXLEN + 1),  # Name too long
        "my/artifact",  # Invalid character(s)
    ),
)
def test_artifact_error_for_invalid_name(tmp_path: Path, api: Api, invalid_name: str):
    """When logging a *file*, passing an invalid artifact name to `Run.log_artifact()` should raise an error."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("test data")

    # It should not be possible to log the artifact
    with raises(ValueError):
        with wandb.init() as run:
            logged = run.log_artifact(file_path, name=invalid_name)
            logged.wait()

    # It should not be possible to retrieve the artifact either
    with raises(CommError):
        api.artifact(f"{invalid_name}:latest")


def test_artifact_upsert_no_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Upsert without a group or id should fail
    with wandb.init() as run:
        artifact = Artifact(name=artifact_name, type=artifact_type)
        image = wandb.Image(np.random.randint(0, 255, (10, 10)))
        artifact.add(image, "image_1")
        with raises(TypeError):
            run.upsert_artifact(artifact)


def test_artifact_upsert_group_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a group should succeed
    with wandb.init(group=group_name) as run:
        artifact = Artifact(name=artifact_name, type=artifact_type)
        image = wandb.Image(np.random.randint(0, 255, (10, 10)))
        artifact.add(image, "image_1")
        run.upsert_artifact(artifact)


def test_artifact_upsert_distributed_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a distributed_id should succeed
    with wandb.init() as run:
        artifact = Artifact(name=artifact_name, type=artifact_type)
        image = wandb.Image(np.random.randint(0, 255, (10, 10)))
        artifact.add(image, "image_2")
        run.upsert_artifact(artifact, distributed_id=group_name)


def test_artifact_finish_no_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Finish without a distributed_id should fail
    with wandb.init() as run:
        artifact = Artifact(artifact_name, type=artifact_type)
        with raises(TypeError):
            run.finish_artifact(artifact)


def test_artifact_finish_group_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    with wandb.init(group=group_name) as run:
        artifact = Artifact(artifact_name, type=artifact_type)
        run.finish_artifact(artifact)


def test_artifact_finish_distributed_id():
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    with wandb.init() as run:
        artifact = Artifact(artifact_name, type=artifact_type)
        run.finish_artifact(artifact, distributed_id=group_name)


@mark.parametrize("incremental", [False, True])
def test_add_file_respects_incremental(tmp_path: Path, api: Api, incremental: bool):
    art_name = "incremental-test"
    art_type = "dataset"

    # Setup: create and log the original artifact
    orig_filepath = tmp_path / "orig.txt"
    orig_filepath.write_text("orig data")
    with wandb.init() as orig_run:
        orig_artifact = Artifact(art_name, art_type)
        orig_artifact.add_file(str(orig_filepath))

        orig_run.log_artifact(orig_artifact)

    # Now add data from a new file to the same artifact, with or without `incremental=True`
    new_filepath = tmp_path / "new.txt"
    new_filepath.write_text("new data")
    with wandb.init() as new_run:
        new_artifact = Artifact(art_name, art_type, incremental=incremental)
        new_artifact.add_file(str(new_filepath))

        new_run.log_artifact(new_artifact)

    # If `incremental=True` was used, expect both files in the artifact.  If not, expect only the last one.
    final_artifact = api.artifact(f"{art_name}:latest")
    final_manifest_entry_keys = final_artifact.manifest.entries.keys()
    if incremental is True:
        assert final_manifest_entry_keys == {orig_filepath.name, new_filepath.name}
    else:
        assert final_manifest_entry_keys == {new_filepath.name}


@mark.flaky
@mark.xfail(reason="flaky on CI")
def test_edit_after_add():
    artifact = Artifact(name="hi-art", type="dataset")
    filename = "file1.txt"
    open(filename, "w").write("hello!")
    artifact.add_file(filename)
    open(filename, "w").write("goodbye.")
    with wandb.init() as run:
        run.log_artifact(artifact)
        artifact.wait()
    with wandb.init() as run:
        art_path = run.use_artifact("hi-art:latest").download()

    # The file from the retrieved artifact should match the original.
    assert open(os.path.join(art_path, filename)).read() == "hello!"
    # While the local file should have the edit applied.
    assert open(filename).read() == "goodbye."


def test_remove_after_log():
    with wandb.init() as run:
        artifact = Artifact(name="hi-art", type="dataset")
        artifact.add_reference(Path(__file__).as_uri())
        run.log_artifact(artifact)
        artifact.wait()

    with wandb.init() as run:
        retrieved = run.use_artifact("hi-art:latest")

        with raises(ArtifactFinalizedError):
            retrieved.remove("file1.txt")


@mark.usefixtures("override_env_dirs")
@mark.parametrize(
    # Valid values for `skip_cache` in `Artifact.download()`
    "skip_download_cache",
    [None, False, True],
)
def test_download_respects_skip_cache(tmp_path: Path, skip_download_cache: bool):
    cache = get_artifact_file_cache()

    artifact = Artifact(name="cache-test", type="dataset")
    orig_content = "test123"
    file_path = Path(tmp_path / "text.txt")
    file_path.write_text(orig_content)

    # Don't skip cache for setup
    entry = artifact.add_file(file_path, policy="immutable", skip_cache=True)

    with wandb.init() as run:
        run.log_artifact(artifact)
    artifact.wait()

    # Ensure the uploaded file is in the cache.
    cache_pathstr, hit, _ = cache.check_md5_obj_path(entry.digest, entry.size)
    assert not hit

    # Manually write a file into the cache path to check that it's:
    # - used, if not skipping the cache (default behavior)
    # - ignored, if skipping the cache
    # This is kind of evil and might break if we later force cache validity.
    replaced_cache_content = "corrupt"

    cache_path = Path(cache_pathstr)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(replaced_cache_content)

    dest_dir = tmp_path / "download_root"
    download_root = Path(artifact.download(dest_dir, skip_cache=skip_download_cache))
    downloaded_content = (download_root / "text.txt").read_text()

    if skip_download_cache in (None, False):
        assert downloaded_content == replaced_cache_content
        assert downloaded_content != orig_content
    else:
        assert downloaded_content != replaced_cache_content
        assert downloaded_content == orig_content


# Use a separate staging directory for the duration of this test.
@mark.usefixtures("override_env_dirs")
def test_uploaded_artifacts_are_unstaged(temp_staging_dir: Path):
    def dir_size(root: Path):
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

    data_path = Path("random.bin")
    data_path.write_bytes(np.random.bytes(4096))

    artifact = Artifact(name="stage-test", type="dataset")
    artifact.add_file(str(data_path))

    # The file is staged until it's finalized.
    assert dir_size(temp_staging_dir) == 4096

    with wandb.init() as run:
        run.log_artifact(artifact)

    # The staging directory should be empty again.
    assert dir_size(temp_staging_dir) == 0


def test_large_manifests_passed_by_file(
    monkeypatch: MonkeyPatch, mocker: MockerFixture
):
    writer_spy = mocker.spy(
        wandb.sdk.interface.interface.InterfaceBase,
        "_write_artifact_manifest_file",
    )
    monkeypatch.setattr(
        wandb.sdk.interface.interface,
        "MANIFEST_FILE_SIZE_THRESHOLD",
        0,
    )

    content = "test content\n"
    with wandb.init() as run:
        artifact = Artifact(name="large-manifest", type="dataset")
        with artifact.new_file("test_file.txt") as f:
            f.write(content)
        artifact.manifest.entries["test_file.txt"].extra["test_key"] = {"x": 1}
        run.log_artifact(artifact)
        artifact.wait()

    assert writer_spy.call_count == 1
    file_written = writer_spy.spy_return
    assert file_written is not None
    # The file should have been cleaned up and deleted by the receiving process.
    assert not os.path.exists(file_written)

    with wandb.init() as run:
        artifact = run.use_artifact("large-manifest:latest")
        assert len(artifact.manifest) == 1
        entry = artifact.manifest.entries.get("test_file.txt")
        assert entry is not None
        assert entry.digest == md5_string(content)
        assert entry.size == len(content)
        assert entry.ref is None
        assert entry.extra["test_key"] == {"x": 1}


# Use a separate staging directory for the duration of this test.
@mark.usefixtures("override_env_dirs")
def test_mutable_uploads_with_cache_enabled(tmp_path: Path, temp_staging_dir: Path):
    cache = get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    data_path.write_text("test 123")
    artifact = Artifact(name="stage-test", type="dataset")
    manifest_entry = artifact.add_file(data_path)

    # The file is staged
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 1
    assert staging_files[0].read_text() == "test 123"

    with wandb.init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert found

    # The staged files are deleted after caching
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0


# Use a separate staging directory for the duration of this test.
@mark.usefixtures("override_env_dirs")
def test_mutable_uploads_with_cache_disabled(tmp_path: Path, temp_staging_dir: Path):
    cache = get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    data_path.write_text("test 123")
    artifact = Artifact(name="stage-test", type="dataset")
    manifest_entry = artifact.add_file(data_path, skip_cache=True)

    # The file is staged
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 1
    assert staging_files[0].read_text() == "test 123"

    with wandb.init() as run:
        run.log_artifact(artifact)

    # The file is not cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert not found

    # The staged files are deleted even if caching is disabled
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0


@mark.usefixtures("override_env_dirs")
def test_immutable_uploads_with_cache_enabled(tmp_path: Path, temp_staging_dir: Path):
    cache = get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    data_path.write_text("test 123")
    artifact = Artifact(name="stage-test", type="dataset")
    manifest_entry = artifact.add_file(data_path, policy="immutable")

    # The file is not staged
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0

    with wandb.init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert found


@mark.usefixtures("override_env_dirs")
def test_immutable_uploads_with_cache_disabled(tmp_path: Path, temp_staging_dir: Path):
    cache = get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    data_path.write_text("test 123")
    artifact = Artifact(name="stage-test", type="dataset")
    manifest_entry = artifact.add_file(data_path, skip_cache=True, policy="immutable")

    # The file is not staged
    staging_files = list(temp_staging_dir.iterdir())
    assert len(staging_files) == 0

    with wandb.init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert not found


def test_local_references():
    with wandb.init() as run:
        t1 = wandb.Table(columns=[], data=[])
        artifact1 = Artifact("test_local_references", "dataset")
        artifact1.add(t1, "t1")
        assert artifact1.manifest.entries["t1.table.json"].ref is None
        run.log_artifact(artifact1)
        artifact2 = Artifact("test_local_references_2", "dataset")
        artifact2.add(t1, "t2")
        assert artifact2.manifest.entries["t2.table.json"].ref is not None


def test_artifact_wait_success():
    # Test artifact wait() timeout parameter
    timeout = 60
    leeway = 0.50
    with wandb.init() as run:
        artifact = Artifact("art", type="dataset")
        start_timestamp = time.time()
        run.log_artifact(artifact).wait(timeout=timeout)
        elapsed_time = time.time() - start_timestamp
        assert elapsed_time < timeout * (1 + leeway)


@mark.parametrize("timeout", [0, 1e-6])
def test_artifact_wait_failure(timeout: float):
    # Test to expect WaitTimeoutError when wait timeout is reached and large image
    # wasn't uploaded yet
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    with wandb.init() as run:
        with raises(WaitTimeoutError):
            artifact = Artifact("art", type="image")
            artifact.add(image, "image")
            run.log_artifact(artifact).wait(timeout=timeout)


@mark.usefixtures("override_env_dirs")
def test_check_existing_artifact_before_download(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    temp_cache_dir: Path,
):
    """Don't re-download an artifact if it's already in the desired location."""
    original_file = tmp_path / "test.txt"
    original_file.write_text("hello")
    with wandb.init() as run:
        artifact = Artifact("art", type="dataset")
        artifact.add_file(original_file)
        run.log_artifact(artifact)

    # Download the artifact
    with wandb.init() as run:
        artifact_path = run.use_artifact("art:latest").download()
        assert os.path.exists(artifact_path)

    # Delete the entire cache
    shutil.rmtree(temp_cache_dir)

    def fail_copy(src, dst):
        raise RuntimeError(f"Should not be called, attempt to copy from {src} to {dst}")

    # Monkeypatch the copy function to fail
    monkeypatch.setattr(shutil, "copy2", fail_copy)

    # Download the artifact again; it should be left in place despite the absent cache.
    with wandb.init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file1 = artifact_path / "test.txt"
        assert file1.is_file()
        assert file1.read_text() == "hello"


def test_check_changed_artifact_then_download(tmp_path: Path):
    """*Do* re-download an artifact if it's been modified in place."""
    original_file = tmp_path / "test.txt"
    original_file.write_text("hello")
    with wandb.init() as run:
        artifact = Artifact("art", type="dataset")
        artifact.add_file(original_file)
        run.log_artifact(artifact)

    # Download the artifact
    with wandb.init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file1 = artifact_path / "test.txt"
        assert file1.is_file()
        assert file1.read_text() == "hello"

    # Modify the artifact file to change its hash.
    file1.write_text("goodbye")

    # Download it again; it should be replaced with the original version.
    with wandb.init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file2 = artifact_path / "test.txt"
        assert file1 == file2  # Same path, but the content should have changed.
        assert file2.is_file()
        assert file2.read_text() == "hello"


@mark.parametrize("path_type", [str, Path])
def test_log_dir_directly(example_files: Path, path_type: type[str | Path]):
    with wandb.init() as run:
        run_id = run.id
        artifact = run.log_artifact(path_type(example_files))
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None  # It was successfully logged.
    assert artifact.name == f"run-{run_id}-{Path(example_files).name}:v0"


@mark.parametrize("path_type", [str, Path])
def test_log_file_directly(example_file: Path, path_type: type[str | Path]):
    with wandb.init() as run:
        run_id = run.id
        artifact = run.log_artifact(path_type(example_file))
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None
    assert artifact.name == f"run-{run_id}-{Path(example_file).name}:v0"


def test_log_reference_directly(example_files: Path):
    with wandb.init() as run:
        run_id = run.id
        artifact = run.log_artifact(example_files.resolve().as_uri())
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None
    assert artifact.name == f"run-{run_id}-{example_files.name}:v0"


@mark.usefixtures("override_env_dirs")
def test_artifact_download_root(logged_artifact: Artifact, temp_artifact_dir: Path):
    name_path = logged_artifact.name
    if platform.system() == "Windows":
        name_path = name_path.replace(":", "-")

    downloaded = Path(logged_artifact.download())
    assert downloaded == temp_artifact_dir / name_path


def test_log_and_download_with_path_prefix(tmp_path: Path):
    artifact = Artifact(name="test-artifact", type="dataset")
    file_paths = [
        tmp_path / "some-prefix" / "one.txt",
        tmp_path / "some-prefix-two.txt",
        tmp_path / "other-thing.txt",
    ]

    # Create files and add them to the artifact
    for file_path in file_paths:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f"Content of {file_path.name}")
    artifact.add_dir(tmp_path)

    with wandb.init() as run:
        run.log_artifact(artifact)

    with wandb.init() as run:
        logged_artifact = run.use_artifact("test-artifact:latest")
        download_dir = Path(logged_artifact.download(path_prefix="some-prefix"))

    # Check that the files with the prefix are downloaded
    assert (download_dir / "some-prefix" / "one.txt").is_file()
    assert (download_dir / "some-prefix-two.txt").is_file()

    # Check that the file without the prefix is not downloaded
    assert not (download_dir / "other-thing.txt").exists()
    shutil.rmtree(download_dir)

    with wandb.init() as run:
        logged_artifact = run.use_artifact("test-artifact:latest")
        download_dir = Path(logged_artifact.download(path_prefix="some-prefix/"))

    # Only the file in the exact subdirectory should download.
    assert (download_dir / "some-prefix" / "one.txt").is_file()
    assert not (download_dir / "some-prefix-two.txt").exists()
    assert not (download_dir / "other-thing.txt").exists()

    shutil.rmtree(download_dir)

    with wandb.init() as run:
        logged_artifact = run.use_artifact("test-artifact:latest")
        download_dir = Path(logged_artifact.download(path_prefix=""))

    # All files should download.
    assert (download_dir / "some-prefix" / "one.txt").is_file()
    assert (download_dir / "some-prefix-two.txt").is_file()
    assert (download_dir / "other-thing.txt").is_file()


def test_retrieve_missing_artifact(logged_artifact: Artifact, api: Api):
    with raises(CommError, match="project 'bar' not found"):
        api.artifact(f"foo/bar/{logged_artifact.name}")

    with raises(CommError, match="project 'bar' not found"):
        api.artifact(f"{logged_artifact.entity}/bar/{logged_artifact.name}")

    with raises(CommError):
        api.artifact(f"{logged_artifact.entity}/{logged_artifact.project}/baz")

    with raises(CommError):
        api.artifact(f"{logged_artifact.entity}/{logged_artifact.project}/baz:v0")


def test_new_draft(api: Api):
    art = Artifact("test-artifact", "test-type")
    with art.new_file("boom.txt", "w") as f:
        f.write("detonation")

    # Set properties that won't be copied.
    art.ttl = None

    project = "test"
    with wandb.init(project=project) as run:
        run.log_artifact(art, aliases=["a"])
        run.link_artifact(art, f"{project}/my-sample-portfolio")

    parent = api.artifact(f"{project}/my-sample-portfolio:latest")
    draft = parent.new_draft()

    # entity/project/name should all match the *source* artifact.
    assert draft.type == art.type
    assert draft.name == "test-artifact"  # No version suffix.
    assert draft._base_id == parent.id  # Parent is the source artifact.

    # We would use public properties, but they're only available on non-draft artifacts.
    assert draft._entity == parent.entity
    assert draft._project == parent.project
    assert draft._source_name == art.name.split(":")[0]
    assert draft._source_entity == parent.entity
    assert draft._source_project == parent.project

    # The draft won't have fields that only exist after being committed.
    assert draft._version is None
    assert draft._source_version is None
    assert draft._ttl_duration_seconds is None
    assert draft._ttl_is_inherited
    assert not draft._ttl_changed
    assert draft._aliases == []
    assert draft._saved_aliases == []
    assert draft.is_draft()
    assert draft._created_at is None
    assert draft._updated_at is None
    assert not draft._final

    # Add a file and log the new draft.
    with draft.new_file("bang.txt", "w") as f:
        f.write("expansion")

    with wandb.init(project=project) as run:
        run.log_artifact(draft)

    child = api.artifact(f"{project}/test-artifact:latest")
    assert child.version == "v1"

    assert len(child.manifest.entries) == 2
    file_path = child.download()
    assert os.path.exists(os.path.join(file_path, "boom.txt"))
    assert os.path.exists(os.path.join(file_path, "bang.txt"))


def test_get_artifact_collection(logged_artifact: Artifact):
    collection = logged_artifact.collection
    assert logged_artifact.entity == collection.entity
    assert logged_artifact.project == collection.project
    assert logged_artifact.name.startswith(collection.name)
    assert logged_artifact.type == collection.type


def test_used_artifacts_preserve_original_project(
    user: str,
    api: Api,
    logged_artifact: Artifact,
):
    """Run artifacts from the API should preserve the original project they were created in."""
    orig_project = logged_artifact.project  # Original project that created the artifact
    new_project = "new-project"  # New project using the same artifact

    artifact_path = f"{user}/{orig_project}/{logged_artifact.name}"

    # Use the artifact within a *different* project
    with wandb.init(entity=user, project=new_project) as run:
        art = run.use_artifact(artifact_path)
        art.download()

    # Check project of artifact vs run as retrieved from the API
    run_from_api = api.run(run.path)
    art_from_run = run_from_api.used_artifacts()[0]

    # Assumption check in case of future changes to fixtures
    assert orig_project != new_project

    assert run_from_api.project == new_project
    assert art_from_run.project == orig_project


def test_internal_artifacts():
    internal_type = f"{RESERVED_ARTIFACT_TYPE_PREFIX}invalid"
    with wandb.init() as run:
        with raises(ValueError, match="is reserved for internal use"):
            artifact = Artifact(name="test-artifact", type=internal_type)

        artifact = InternalArtifact(name="test-artifact", type=internal_type)
        run.log_artifact(artifact)


def test_storage_policy_storage_region(user: str, api: Api, tmp_path: Path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("test data")
    project = "test"
    with wandb.init(entity=user, project=project) as run:
        # Set in onprem/local/scripts/env.txt when building the test container from gorilla.
        art = Artifact(
            "test-storage-region", type="dataset", storage_region="minio-local"
        )
        art.add_file(file_path)
        run.log_artifact(art)
        art.wait()

    # Able to download the file
    art = api.artifact(f"{user}/{project}/test-storage-region:latest")
    art.download()
    assert os.path.exists(file_path)
    assert open(file_path).read() == "test data"

    # Manifest should have the storage region
    manifest = art.manifest.to_manifest_json()
    assert manifest["storagePolicyConfig"]["storageRegion"] == "minio-local"


def test_storage_policy_storage_region_not_available():
    with wandb.init() as run:
        # NOTE: We match on the region name instead of exact API error because different versions of server fails at different APIs.
        # In latest version, storageRegion is passed in `CreateArtifact` and it would return soemthing like `CreateArtifact invalid storageRegion: coreweave-us`
        # In previous version, storageRegion is ignored in graphql APIs but used in `CommitArtifact` from manifest json and ther error is `malformed region: coreweave-us`
        with raises(ValueError, match="coreweave-us"):
            art = Artifact("test", type="dataset", storage_region="coreweave-us")
            run.log_artifact(art)
            art.wait()


@responses.activate()
def test_artifact_multipart_download_refresh_presigned_url(
    user: str,
    api: Api,
    tmp_path: Path,
):
    # Let graphql and manifest json (also stored on S3) passthrough.
    responses.add_passthru(re.compile(r".*graphql.*"))
    responses.add_passthru(re.compile(r".*wandb_manifest\.json.*"))

    all_s3_requests = []

    def s3_request_callback(request):
        all_s3_requests.append(request.url)

        if len(all_s3_requests) == 1:
            return (403, {}, b"AccessDenied: Request has expired")
        if len(all_s3_requests) == 2:
            return (500, {}, b"500 retry the same url without refresh")
        else:
            return (200, {}, b"test data for retry")

    # manifest json is not stored under wandb_artifacts/, only the file blobs are.
    responses.add_callback(
        responses.GET,
        re.compile(r".*wandb_artifacts/.*"),
        callback=s3_request_callback,
    )

    file_path = tmp_path / "test.txt"
    file_path.write_text("test data for retry")
    project = "test"

    with wandb.init(entity=user, project=project) as run:
        art = Artifact("test-retry-expired-download-url", type="dataset")
        art.add_file(file_path)
        run.log_artifact(art)
        art.wait()

    art = api.artifact(f"{user}/{project}/test-retry-expired-download-url:latest")
    # NOTE: We need to use multipart=True to avoid triggering non multipart's retry
    # logic, which is using the `aritifactsV2` handler to redirect to presigned url
    # instead of calling graphql to get the download url (directUrl).
    download_path = art.download(skip_cache=True, multipart=True)

    downloaded_file = Path(download_path) / "test.txt"
    assert downloaded_file.exists(), f"File not found at {downloaded_file}"
    assert downloaded_file.read_text() == "test data for retry"

    assert len(all_s3_requests) == 3, (
        f"Expected 3 calls (initial 403 + refresh URL then 500 + built-in retry 200), got {len(all_s3_requests)}. "
        f"Requests: {all_s3_requests}"
    )
