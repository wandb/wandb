from __future__ import annotations

import errno
import os
import random
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import wandb
from pydantic import ValidationError
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest import mark, raises
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.artifacts.storage_handler import StorageHandler, _BaseStorageHandler
from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
from wandb.sdk.artifacts.storage_handlers.local_file_handler import LocalFileHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.artifacts.storage_handlers.wb_artifact_handler import WBArtifactHandler
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.lib.hashutil import ETag, md5_string

example_digest = md5_string("example")


def test_opener_rejects_append_mode(artifact_file_cache):
    _, _, opener = artifact_file_cache.check_md5_obj_path(example_digest, 7)

    with raises(ValueError):
        with opener("a"):
            pass

    # make sure that the ValueError goes away if we use a valid mode
    with opener("w") as f:
        f.write("example")


def test_opener_works_across_filesystem_boundaries(
    tmp_path,
    artifact_file_cache,
    fs: FakeFilesystem,
):
    # This isn't ideal, we'd rather test e.g. `Artifact.download` directly.
    #
    # However, we're using `pyfakefs` to mock mounted/partitioned filesystems,
    # and it doesn't play well with some of the internals of ArtifactFileCache
    # without extra, potentially brittle patches (e.g. to `subprocess.call`).
    # This will have to do for the moment.

    # Some setup we have to do to get this test to play well with `pyfakefs`.
    # Note: Cast to str looks redundant but is intentional (for python<=3.10).
    # https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests
    fake_tmp_path = Path(str(tmp_path))
    fs.create_dir(fake_tmp_path)

    fake_cache_dir = Path(str(artifact_file_cache._cache_dir))
    fake_cache_obj_dir = Path(str(artifact_file_cache._obj_dir))
    fake_cache_temp_dir = Path(str(artifact_file_cache._temp_dir))
    artifact_file_cache._cache_dir = fake_cache_dir
    artifact_file_cache._obj_dir = fake_cache_obj_dir
    artifact_file_cache._temp_dir = fake_cache_temp_dir
    fs.create_dir(fake_cache_dir)
    fs.create_dir(fake_cache_obj_dir)
    fs.create_dir(fake_cache_temp_dir)

    cache_path, _, cache_opener = artifact_file_cache.check_md5_obj_path(
        example_digest, 7
    )
    with cache_opener() as f:
        f.write("test-123")

    # Simulate a destination filepath on the mounted filesystem
    dest_dir = fake_tmp_path / "mount"
    dest_path = dest_dir / "dest.txt"
    fs.create_dir(dest_dir)
    fs.add_mount_point(str(dest_dir))

    # Sanity check: `os.rename` should fail across the (fake) filesystem boundary
    # This is extra assurance that we're still testing what we expect to test
    with raises(OSError) as excinfo:
        os.rename(cache_path, dest_path)
    assert excinfo.value.args[0] == errno.EXDEV

    # Now simulate skipping the cache
    artifact_file_cache._override_cache_path = dest_path
    override_path, _, override_opener = artifact_file_cache.check_md5_obj_path(
        example_digest, 7
    )

    with override_opener() as f:
        f.write("test-abc")

    assert dest_path.read_text() == "test-abc"


def test_check_md5_obj_path(artifact_file_cache):
    md5 = md5_string("hi")
    path, exists, opener = artifact_file_cache.check_md5_obj_path(md5, 2)
    expected_path = os.path.join(
        artifact_file_cache._cache_dir,
        "obj",
        "md5",
        "49",
        "f68a5c8493ec2c0bf489821c21fc3b",
    )
    assert path == expected_path

    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert exists is False
    assert contents == "hi"


def test_check_md5_obj_path_override(artifact_file_cache):
    md5 = md5_string("hi")
    override_path = os.path.join(artifact_file_cache._cache_dir, "override.cache")
    artifact_file_cache._override_cache_path = override_path
    path, exists, _ = artifact_file_cache.check_md5_obj_path(md5, 2)
    assert path == override_path
    assert exists is False


def test_check_etag_obj_path_points_to_opener_dst(artifact_file_cache):
    path, _, opener = artifact_file_cache.check_etag_obj_path(
        "http://my/url", "abc", 10
    )

    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert contents == "hi"


def test_check_etag_obj_path_override(artifact_file_cache):
    override_path = os.path.join(artifact_file_cache._cache_dir, "override.cache")
    artifact_file_cache._override_cache_path = override_path
    path, exists, _ = artifact_file_cache.check_etag_obj_path("http://my/url", "abc", 2)
    assert path == override_path
    assert exists is False


def test_check_etag_obj_path_returns_exists_if_exists(artifact_file_cache):
    size = 123
    _, exists, opener = artifact_file_cache.check_etag_obj_path(
        "http://my/url", "abc", size
    )
    assert not exists

    with opener() as f:
        f.write(size * "a")

    _, exists, _ = artifact_file_cache.check_etag_obj_path("http://my/url", "abc", size)
    assert exists


def test_check_etag_obj_path_returns_not_exists_if_incomplete(artifact_file_cache):
    size = 123
    _, exists, opener = artifact_file_cache.check_etag_obj_path(
        "http://my/url", "abc", size
    )
    assert not exists

    with opener() as f:
        f.write((size - 1) * "a")

    _, exists, _ = artifact_file_cache.check_etag_obj_path("http://my/url", "abc", size)
    assert not exists

    with opener() as f:
        f.write(size * "a")

    _, exists, _ = artifact_file_cache.check_etag_obj_path("http://my/url", "abc", size)
    assert exists


def test_check_etag_obj_path_does_not_include_etag(artifact_file_cache):
    path, _, _ = artifact_file_cache.check_etag_obj_path("http://url/1", "abcdef", 10)
    assert "abcdef" not in path


@mark.parametrize(
    ["url1", "url2", "etag1", "etag2", "path_equal"],
    [
        ("http://url/1", "http://url/1", "abc", "abc", True),
        ("http://url/1", "http://url/1", "abc", "def", False),
        ("http://url/1", "http://url/2", "abc", "abc", False),
    ],
)
def test_check_etag_obj_path_hashes_url_and_etag(
    url1, url2, etag1, etag2, path_equal, artifact_file_cache
):
    path_1, _, _ = artifact_file_cache.check_etag_obj_path(url1, etag1, 10)
    path_2, _, _ = artifact_file_cache.check_etag_obj_path(url2, etag2, 10)

    if path_equal:
        assert path_1 == path_2
    else:
        assert path_1 != path_2


# This function should only be used in `test_check_write_parallel`,
# but it needs to be a global function for multiprocessing.
def _cache_writer(artifact_file_cache):
    etag = "abcdef"
    _, _, opener = artifact_file_cache.check_etag_obj_path(
        "http://wandb.ex/foo", etag, 10
    )
    with opener() as f:
        f.write("".join(random.choice("0123456") for _ in range(10)))


@mark.flaky
@mark.xfail(reason="flaky")
def test_check_write_parallel(artifact_file_cache):
    num_parallel = 5

    p = Pool(num_parallel)
    p.map(_cache_writer, [artifact_file_cache for _ in range(num_parallel)])
    _cache_writer(artifact_file_cache)  # run in this process too for code coverage
    p.close()
    p.join()

    # Regardless of the ordering, we should be left with one file at the end.
    files = [
        f
        for f in (artifact_file_cache._cache_dir / "obj" / "etag").rglob("*")
        if f.is_file()
    ]
    assert len(files) == 1


def test_artifact_file_cache_is_writeable(tmp_path, monkeypatch):
    # Patch NamedTemporaryFile to raise a PermissionError
    def not_allowed(*args, **kwargs):
        raise PermissionError

    monkeypatch.setattr(tempfile, "_mkstemp_inner", not_allowed)
    with raises(PermissionError, match="Unable to write to"):
        ArtifactFileCache(tmp_path)


def test_artifact_file_cache_cleanup_empty(artifact_file_cache):
    reclaimed_bytes = artifact_file_cache.cleanup(100000)
    assert reclaimed_bytes == 0


def test_artifact_file_cache_cleanup(artifact_file_cache):
    cache_root = os.path.join(artifact_file_cache._cache_dir, "obj", "md5")

    path_1 = os.path.join(cache_root, "aa")
    os.makedirs(path_1)
    with open(os.path.join(path_1, "aardvark"), "w") as f:
        f.truncate(5000)
        f.flush()
        os.fsync(f)

    path_2 = os.path.join(cache_root, "ab")
    os.makedirs(path_2)
    with open(os.path.join(path_2, "absolute"), "w") as f:
        f.truncate(2000)
        f.flush()
        os.fsync(f)

    path_3 = os.path.join(cache_root, "ac")
    os.makedirs(path_3)
    with open(os.path.join(path_3, "accelerate"), "w") as f:
        f.truncate(1000)
        f.flush()
        os.fsync(f)

    reclaimed_bytes = artifact_file_cache.cleanup(5000)

    # We should get rid of "aardvark" in this case
    assert reclaimed_bytes == 5000


def test_artifact_file_cache_cleanup_tmp_files_when_asked(artifact_file_cache):
    with open(artifact_file_cache._temp_dir / "foo", "w") as f:
        f.truncate(1000)

    # Even if we are above our target size, the cleanup
    # should reclaim tmp files.
    reclaimed_bytes = artifact_file_cache.cleanup(10000, remove_temp=True)

    assert reclaimed_bytes == 1000


def test_artifact_file_cache_cleanup_leaves_tmp_files_by_default(
    artifact_file_cache, capsys
):
    with open(artifact_file_cache._temp_dir / "foo", "w") as f:
        f.truncate(1000)

    # The cleanup should leave temp files alone, even if we haven't reached our target.
    reclaimed_bytes = artifact_file_cache.cleanup(0)
    assert reclaimed_bytes == 0

    # However, it should issue a warning.
    _, stderr = capsys.readouterr()
    assert "Cache contains 1000.0B of temporary files" in stderr


def test_local_file_handler_load_path_uses_cache(artifact_file_cache, tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("hello")
    uri = file.as_uri()
    digest = "XUFAKrxLKna5cZ2REBfFkg=="

    path, _, opener = artifact_file_cache.check_md5_obj_path(b64_md5=digest, size=5)
    with opener() as f:
        f.write("hello")

    handler = LocalFileHandler()

    local_path = handler.load_path(
        ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=digest,
            size=5,
        ),
        local=True,
    )
    assert local_path == path


def test_s3_storage_handler_load_path_uses_cache(artifact_file_cache):
    uri = "s3://some-bucket/path/to/file.json"
    etag = "some etag"

    path, _, opener = artifact_file_cache.check_etag_obj_path(uri, etag, 123)
    with opener() as f:
        f.write(123 * "a")

    handler = S3Handler()

    local_path = handler.load_path(
        ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=etag,
            size=123,
        ),
        local=True,
    )
    assert local_path == path


def test_gcs_storage_handler_load_path_nonlocal():
    uri = "gs://some-bucket/path/to/file.json"
    etag = "some etag"

    handler = GCSHandler()
    local_path = handler.load_path(
        ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=etag,
            size=123,
        ),
        # Default: local=False,
    )
    assert local_path == uri


def test_gcs_storage_handler_load_path_uses_cache(artifact_file_cache):
    uri = "gs://some-bucket/path/to/file.json"
    digest = ETag(md5_string("a" * 123))

    path, _, opener = artifact_file_cache.check_etag_obj_path(uri, digest, 123)
    with opener() as f:
        f.write(123 * "a")

    handler = GCSHandler()

    local_path = handler.load_path(
        ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=digest,
            size=123,
        ),
        local=True,
    )
    assert local_path == path


def test_cache_add_gives_useful_error_when_out_of_space(
    artifact_file_cache,
    mock_wandb_log,
):
    # Ask to create a 1 quettabyte file to ensure the cache won't find room.
    _, _, opener = artifact_file_cache.check_md5_obj_path(example_digest, size=10**30)

    with raises(OSError, match="Insufficient free space"):
        with opener():
            pass

    mock_wandb_log.assert_warned("Cache size exceeded. Attempting to reclaim space...")


# todo: fix this test
# def test_cache_drops_lru_when_adding_not_enough_space(fs, artifact_file_cache):
#     # Simulate a 1KB drive.
#     fs.set_disk_usage(1000)
#
#     # Create a few files to fill up the cache (exactly).
#     cache_paths = []
#     for i in range(10):
#         content = f"{i}" * 100
#         path, _, opener = artifact_file_cache.check_md5_obj_path(md5_string(content), 100)
#         with opener() as f:
#             f.write(content)
#         cache_paths.append(path)
#
#     # This next file won't fit; we should drop 1/2 the files in LRU order.
#     _, _, opener = artifact_file_cache.check_md5_obj_path(md5_string("x"), 1)
#     with opener() as f:
#         f.write("x")
#
#     for path in cache_paths[:5]:
#         assert not os.path.exists(path)
#     for path in cache_paths[5:]:
#         assert os.path.exists(path)
#
#     assert fs.get_disk_usage()[1] == 501
#
#     # Add something big enough that removing half the items isn't enough.
#     _, _, opener = artifact_file_cache.check_md5_obj_path(md5_string("y" * 800), 800)
#     with opener() as f:
#         f.write("y" * 800)
#
#     # All paths should have been removed, and the usage is just the new file size.
#     for path in cache_paths:
#         assert not os.path.exists(path)
#     assert fs.get_disk_usage()[1] == 800


def test_cache_add_cleans_up_tmp_when_write_fails(artifact_file_cache, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError

    _, _, opener = artifact_file_cache.check_md5_obj_path(
        b64_md5=example_digest, size=7
    )

    with raises(OSError):
        with opener() as f:
            f.write("example")
            f.flush()
            os.fsync(f.fileno())

            path = f.name
            assert os.path.exists(path)

            monkeypatch.setattr(os, "replace", fail)

    assert not os.path.exists(path)


class FakePublicApi:
    @property
    def client(self):
        return None


def test_wbartifact_handler_load_path_nonlocal(monkeypatch):
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    artifact = wandb.Artifact("test", type="dataset")
    manifest_entry = ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = WBArtifactHandler()
    handler._client = FakePublicApi()
    monkeypatch.setattr(Artifact, "_from_id", lambda _1, _2: artifact)
    artifact.get_entry = lambda _: artifact
    artifact.ref_target = lambda: uri

    local_path = handler.load_path(manifest_entry)
    assert local_path == uri


def test_wbartifact_handler_load_path_local(monkeypatch):
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    artifact = wandb.Artifact("test", type="dataset")
    manifest_entry = ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = WBArtifactHandler()
    handler._client = FakePublicApi()
    monkeypatch.setattr(Artifact, "_from_id", lambda _1, _2: artifact)
    artifact.get_entry = lambda _: artifact
    artifact.download = lambda: path

    local_path = handler.load_path(manifest_entry, local=True)
    assert local_path == path


class UnfinishedStoragePolicy(StoragePolicy):
    @classmethod
    def name(cls) -> str:
        return "UnfinishedStoragePolicy"


def test_storage_policy_incomplete():
    policy = StoragePolicy.lookup_by_name("UnfinishedStoragePolicy")
    assert policy is UnfinishedStoragePolicy

    with raises(ValueError, match="Failed to find storage policy"):
        StoragePolicy.lookup_by_name("NotAStoragePolicy")


def test_storage_handler_incomplete():
    class UnfinishedStorageHandler(_BaseStorageHandler):
        pass

    # Instantiation should fail if the StorageHandler impl doesn't fully implement all abstract methods.
    with raises(TypeError):
        UnfinishedStorageHandler()

    class UnfinishedSingleStorageHandler(StorageHandler):
        pass

    with raises(TypeError):
        UnfinishedSingleStorageHandler()


def test_unwritable_staging_dir(monkeypatch):
    # Use a non-writable directory as the staging directory.
    # CI just doesn't care about permissions, so we're patching os.makedirs 🙃
    def nope(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "makedirs", nope)

    with raises(PermissionError, match="WANDB_DATA_DIR"):
        get_staging_dir()


def test_invalid_upload_policy():
    path = "foo/bar"
    artifact = wandb.Artifact("test", type="dataset")
    with raises(ValueError):
        artifact.add_file(local_path=path, name="file.json", policy="tmp")
    with raises(ValueError):
        artifact.add_dir(local_path=path, policy="tmp")


@mark.parametrize(
    "storage_region",
    [
        None,
        "coreweave-us",
        "coreweave-404",  # local validation won't check against server for actual supported regions
    ],
)
def test_artifact_with_valid_storage_region(storage_region: str):
    wandb.Artifact("test", type="dataset", storage_region=storage_region)


@mark.parametrize(
    "storage_region",
    [
        "",
        " ",
        123,
    ],
)
def test_artifact_with_invalid_storage_region(storage_region: Any):
    with raises(ValidationError):
        wandb.Artifact("test", type="dataset", storage_region=storage_region)
