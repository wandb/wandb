import os
import platform
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import wandb
from wandb import Api
from wandb.errors import CommError
from wandb.sdk.artifacts import artifact_file_cache
from wandb.sdk.artifacts.exceptions import ArtifactFinalizedError, WaitTimeoutError
from wandb.sdk.artifacts.staging import get_staging_dir

sm = wandb.wandb_sdk.internal.sender.SendManager


def test_add_table_from_dataframe(wandb_init):
    import pandas as pd

    df_float = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float_)
    df_float32 = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float32)
    df_bool = pd.DataFrame([[True, False, True]], dtype=np.bool_)

    current_time = datetime.now()
    df_timestamp = pd.DataFrame(
        [[current_time + timedelta(days=i)] for i in range(10)], columns=["date"]
    )

    wb_table_float = wandb.Table(dataframe=df_float)
    wb_table_float32 = wandb.Table(dataframe=df_float32)
    wb_table_float32_recast = wandb.Table(dataframe=df_float32.astype(np.float_))
    wb_table_bool = wandb.Table(dataframe=df_bool)
    wb_table_timestamp = wandb.Table(dataframe=df_timestamp)

    run = wandb_init()
    artifact = wandb.Artifact("table-example", "dataset")
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

    run.finish()


def test_artifact_error_for_invalid_aliases(wandb_init):
    run = wandb_init()
    artifact = wandb.Artifact("test-artifact", "dataset")
    error_aliases = [["latest", "workflow:boom"], ["workflow/boom/test"]]
    for aliases in error_aliases:
        with pytest.raises(ValueError) as e_info:
            run.log_artifact(artifact, aliases=aliases)
            assert (
                str(e_info.value)
                == "Aliases must not contain any of the following characters: /, :"
            )

    for aliases in [["latest", "boom_test-q"]]:
        run.log_artifact(artifact, aliases=aliases)

    run.finish()


def test_artifact_upsert_no_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Upsert without a group or id should fail
    run = wandb_init()
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    with pytest.raises(TypeError):
        run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_group_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a group should succeed
    run = wandb_init(group=group_name)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_distributed_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a distributed_id should succeed
    run = wandb_init()
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_2")
    run.upsert_artifact(artifact, distributed_id=group_name)
    run.finish()


def test_artifact_finish_no_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Finish without a distributed_id should fail
    run = wandb_init()
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    with pytest.raises(TypeError):
        run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_group_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb_init(group=group_name)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_distributed_id(wandb_init):
    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb_init()
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact, distributed_id=group_name)
    run.finish()


# this test hangs, which seems to be the result of incomplete mocks.
# would be worth returning to it in the future
# def test_artifact_incremental( relay_server, parse_ctx, test_settings):
#
#         open("file1.txt", "w").write("hello")
#         run = wandb.init(settings=test_settings)
#         artifact = wandb.Artifact(type="dataset", name="incremental_test_PENDING", incremental=True)
#         artifact.add_file("file1.txt")
#         run.log_artifact(artifact)
#         run.finish()

#         manifests_created = parse_ctx(relay_server.get_ctx()).manifests_created
#         assert manifests_created[0]["type"] == "INCREMENTAL"


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky on CI")
def test_edit_after_add(wandb_init):
    artifact = wandb.Artifact(name="hi-art", type="dataset")
    filename = "file1.txt"
    open(filename, "w").write("hello!")
    artifact.add_file(filename)
    open(filename, "w").write("goodbye.")
    with wandb_init() as run:
        run.log_artifact(artifact)
        artifact.wait()
    with wandb_init() as run:
        art_path = run.use_artifact("hi-art:latest").download()

    # The file from the retrieved artifact should match the original.
    assert open(os.path.join(art_path, filename)).read() == "hello!"
    # While the local file should have the edit applied.
    assert open(filename).read() == "goodbye."


def test_remove_after_log(wandb_init):
    with wandb_init() as run:
        artifact = wandb.Artifact(name="hi-art", type="dataset")
        artifact.add_reference(Path(__file__).as_uri())
        run.log_artifact(artifact)
        artifact.wait()

    with wandb_init() as run:
        retrieved = run.use_artifact("hi-art:latest")

        with pytest.raises(ArtifactFinalizedError):
            retrieved.remove("file1.txt")


def test_download_uses_cache(wandb_init, tmp_path, monkeypatch):
    # Setup cache dir
    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path))
    cache = artifact_file_cache.get_artifact_file_cache()

    artifact = wandb.Artifact(name="cache-test", type="dataset")
    file_path = Path(tmp_path / "text.txt")
    with open(file_path, "w") as f:
        f.write("test123")
    entry = artifact.add_file(file_path, policy="immutable", skip_cache=True)

    with wandb_init() as run:
        run.log_artifact(artifact)
    artifact.wait()

    # Ensure the uploaded file is in the cache.
    cache_path, hit, _ = cache.check_md5_obj_path(entry.digest, entry.size)
    assert not hit

    # Manually write a file into the cache path to ensure that it's the one that is used.
    # This is kind of evil and might break if we later force cache validity.
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        f.write("corrupt")
    download_root = Path(artifact.download(tmp_path / "download_root"))
    assert (download_root / "text.txt").read_text() == "corrupt"


def test_uploaded_artifacts_are_unstaged(wandb_init, tmp_path, monkeypatch):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path))
    staging_dir = Path(get_staging_dir())

    def dir_size():
        return sum(f.stat().st_size for f in staging_dir.rglob("*") if f.is_file())

    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open("random.bin", "wb") as f:
        f.write(np.random.bytes(4096))
    artifact.add_file("random.bin")

    # The file is staged until it's finalized.
    assert dir_size() == 4096

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The staging directory should be empty again.
    assert dir_size() == 0


def test_mutable_uploads_with_cache_enabled(wandb_init, tmp_path, monkeypatch, api):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path / "staging"))
    staging_dir = Path(get_staging_dir())

    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path / "cache"))
    cache = artifact_file_cache.get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open(data_path, "w") as f:
        f.write("test 123")
    manifest_entry = artifact.add_file(data_path)

    # The file is staged
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 1
    assert staging_files[0].read_text() == "test 123"

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert found

    # The staged files are deleted after caching
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0


def test_mutable_uploads_with_cache_disabled(wandb_init, tmp_path, monkeypatch):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path / "staging"))
    staging_dir = Path(get_staging_dir())

    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path / "cache"))
    cache = artifact_file_cache.get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open(data_path, "w") as f:
        f.write("test 123")
    manifest_entry = artifact.add_file(data_path, skip_cache=True)

    # The file is staged
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 1
    assert staging_files[0].read_text() == "test 123"

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The file is not cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert not found

    # The staged files are deleted even if caching is disabled
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0


def test_immutable_uploads_with_cache_enabled(wandb_init, tmp_path, monkeypatch):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path / "staging"))
    staging_dir = Path(get_staging_dir())

    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path / "cache"))
    cache = artifact_file_cache.get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open(data_path, "w") as f:
        f.write("test 123")
    manifest_entry = artifact.add_file(data_path, policy="immutable")

    # The file is not staged
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert found


def test_immutable_uploads_with_cache_disabled(wandb_init, tmp_path, monkeypatch):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path / "staging"))
    staging_dir = Path(get_staging_dir())

    monkeypatch.setenv("WANDB_CACHE_DIR", str(tmp_path / "cache"))
    cache = artifact_file_cache.get_artifact_file_cache()

    data_path = Path(tmp_path / "random.txt")
    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open(data_path, "w") as f:
        f.write("test 123")
    manifest_entry = artifact.add_file(data_path, skip_cache=True, policy="immutable")

    # The file is not staged
    staging_files = list(staging_dir.iterdir())
    assert len(staging_files) == 0

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The file is cached
    _, found, _ = cache.check_md5_obj_path(manifest_entry.digest, manifest_entry.size)
    assert not found


def test_local_references(wandb_init):
    run = wandb_init()

    def make_table():
        return wandb.Table(columns=[], data=[])

    t1 = make_table()
    artifact1 = wandb.Artifact("test_local_references", "dataset")
    artifact1.add(t1, "t1")
    assert artifact1.manifest.entries["t1.table.json"].ref is None
    run.log_artifact(artifact1)
    artifact2 = wandb.Artifact("test_local_references_2", "dataset")
    artifact2.add(t1, "t2")
    assert artifact2.manifest.entries["t2.table.json"].ref is not None
    run.finish()


def test_artifact_wait_success(wandb_init):
    # Test artifact wait() timeout parameter
    timeout = 60
    leeway = 0.50
    run = wandb_init()
    artifact = wandb.Artifact("art", type="dataset")
    start_timestamp = time.time()
    run.log_artifact(artifact).wait(timeout=timeout)
    elapsed_time = time.time() - start_timestamp
    assert elapsed_time < timeout * (1 + leeway)
    run.finish()


@pytest.mark.parametrize("timeout", [0, 1e-6])
def test_artifact_wait_failure(wandb_init, timeout):
    # Test to expect WaitTimeoutError when wait timeout is reached and large image
    # wasn't uploaded yet
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    run = wandb_init()
    with pytest.raises(WaitTimeoutError):
        artifact = wandb.Artifact("art", type="image")
        artifact.add(image, "image")
        run.log_artifact(artifact).wait(timeout=timeout)
    run.finish()


def test_check_existing_artifact_before_download(wandb_init, tmp_path, monkeypatch):
    """Don't re-download an artifact if it's already in the desired location."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("WANDB_CACHE_DIR", str(cache_dir))

    original_file = tmp_path / "test.txt"
    original_file.write_text("hello")
    with wandb_init() as run:
        artifact = wandb.Artifact("art", type="dataset")
        artifact.add_file(original_file)
        run.log_artifact(artifact)

    # Download the artifact
    with wandb_init() as run:
        artifact_path = run.use_artifact("art:latest").download()
        assert os.path.exists(artifact_path)

    # Delete the entire cache
    shutil.rmtree(cache_dir)

    def fail_copy(src, dst):
        raise RuntimeError(f"Should not be called, attempt to copy from {src} to {dst}")

    # Monkeypatch the copy function to fail
    monkeypatch.setattr(shutil, "copy2", fail_copy)

    # Download the artifact again; it should be left in place despite the absent cache.
    with wandb_init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file1 = artifact_path / "test.txt"
        assert file1.is_file()
        assert file1.read_text() == "hello"


def test_check_changed_artifact_then_download(wandb_init, tmp_path):
    """*Do* re-download an artifact if it's been modified in place."""
    original_file = tmp_path / "test.txt"
    original_file.write_text("hello")
    with wandb_init() as run:
        artifact = wandb.Artifact("art", type="dataset")
        artifact.add_file(original_file)
        run.log_artifact(artifact)

    # Download the artifact
    with wandb_init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file1 = artifact_path / "test.txt"
        assert file1.is_file()
        assert file1.read_text() == "hello"

    # Modify the artifact file to change its hash.
    file1.write_text("goodbye")

    # Download it again; it should be replaced with the original version.
    with wandb_init() as run:
        artifact_path = Path(run.use_artifact("art:latest").download())
        file2 = artifact_path / "test.txt"
        assert file1 == file2  # Same path, but the content should have changed.
        assert file2.is_file()
        assert file2.read_text() == "hello"


@pytest.mark.parametrize("path_type", [str, Path])
def test_log_dir_directly(example_files, wandb_init, path_type):
    with wandb_init() as run:
        run_id = run.id
        artifact = run.log_artifact(path_type(example_files))
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None  # It was successfully logged.
    assert artifact.name == f"run-{run_id}-{Path(example_files).name}:v0"


@pytest.mark.parametrize("path_type", [str, Path])
def test_log_file_directly(example_file, wandb_init, path_type):
    with wandb_init() as run:
        run_id = run.id
        artifact = run.log_artifact(path_type(example_file))
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None
    assert artifact.name == f"run-{run_id}-{Path(example_file).name}:v0"


def test_log_reference_directly(example_files, wandb_init):
    with wandb_init() as run:
        run_id = run.id
        artifact = run.log_artifact(example_files.resolve().as_uri())
    artifact.wait()

    assert artifact is not None
    assert artifact.id is not None
    assert artifact.name == f"run-{run_id}-{example_files.name}:v0"


def test_artifact_download_root(logged_artifact, monkeypatch, tmp_path):
    art_dir = tmp_path / "an-unusual-path"
    monkeypatch.setenv("WANDB_ARTIFACT_DIR", str(art_dir))
    name_path = logged_artifact.name
    if platform.system() == "Windows":
        name_path = name_path.replace(":", "-")

    downloaded = Path(logged_artifact.download())
    assert downloaded == art_dir / name_path


def test_retrieve_missing_artifact(logged_artifact):
    with pytest.raises(CommError, match="project 'bar' not found"):
        Api().artifact(f"foo/bar/{logged_artifact.name}")

    with pytest.raises(CommError, match="project 'bar' not found"):
        Api().artifact(f"{logged_artifact.entity}/bar/{logged_artifact.name}")

    with pytest.raises(CommError, match="must be specified as 'collection:alias'"):
        Api().artifact(f"{logged_artifact.entity}/{logged_artifact.project}/baz")

    with pytest.raises(CommError, match="do not have permission"):
        Api().artifact(f"{logged_artifact.entity}/{logged_artifact.project}/baz:v0")


def test_new_draft(wandb_init):
    art = wandb.Artifact("test-artifact", "test-type")
    with art.new_file("boom.txt", "w") as f:
        f.write("detonation")

    # Set properties that won't be copied.
    art.ttl = None

    project = "test"
    with wandb_init(project=project) as run:
        run.log_artifact(art, aliases=["a"])
        run.link_artifact(art, f"{project}/my-sample-portfolio")

    parent = Api().artifact(f"{project}/my-sample-portfolio:latest")
    draft = parent.new_draft()

    # entity/project/name should all match the *source* artifact.
    assert draft.type == art.type
    assert draft.name == "test-artifact"  # No version suffix.
    assert draft._base_id == parent.id  # Parent is the source artifact.

    # We would use public properties, but they're only available on non-draft artifacts.
    assert draft._entity == parent.entity
    assert draft._project == parent.project
    assert draft._source_name == art.name
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

    with wandb_init(project=project) as run:
        run.log_artifact(draft)

    child = Api().artifact(f"{project}/test-artifact:latest")
    assert child.version == "v1"

    assert len(child.manifest.entries) == 2
    file_path = child.download()
    assert os.path.exists(os.path.join(file_path, "boom.txt"))
    assert os.path.exists(os.path.join(file_path, "bang.txt"))


def test_get_artifact_collection(logged_artifact):
    collection = logged_artifact.collection
    assert logged_artifact.entity == collection.entity
    assert logged_artifact.project == collection.project
    assert logged_artifact.name.startswith(collection.name)
    assert logged_artifact.type == collection.type


def test_get_artifact_collection_from_linked_artifact(linked_artifact):
    collection = linked_artifact.collection
    assert linked_artifact.entity == collection.entity
    assert linked_artifact.project == collection.project
    assert linked_artifact.name.startswith(collection.name)
    assert linked_artifact.type == collection.type

    collection = linked_artifact.source_collection
    assert linked_artifact.source_entity == collection.entity
    assert linked_artifact.source_project == collection.project
    assert linked_artifact.source_name.startswith(collection.name)
    assert linked_artifact.type == collection.type
