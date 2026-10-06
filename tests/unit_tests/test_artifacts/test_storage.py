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
from wandb import env
from wandb.sdk.artifacts._generated.enums import ArtifactDigestAlgorithm
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.artifacts.storage_handler import StorageHandler, _BaseStorageHandler
from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
from wandb.sdk.artifacts.storage_handlers.local_file_handler import LocalFileHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.artifacts.storage_handlers.wb_artifact_handler import WBArtifactHandler
from wandb.sdk.artifacts.storage_policies.wandb_storage_policy import WandbStoragePolicy
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.lib.hashutil import ETag, b64_to_hex_id, md5_string, xxh128_string

example_digest = md5_string("example")


def test_opener_rejects_append_mode(artifact_file_cache):
    _, _, opener = artifact_file_cache.check_digest_obj_path(example_digest, 7)

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

    cache_path, _, cache_opener = artifact_file_cache.check_digest_obj_path(
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
    override_path, _, override_opener = artifact_file_cache.check_digest_obj_path(
        example_digest, 7, dest_path=dest_path
    )

    with override_opener() as f:
        f.write("test-abc")

    assert dest_path.read_text() == "test-abc"


def test_check_digest_obj_path_md5(artifact_file_cache):
    md5 = md5_string("hi")
    path, exists, opener = artifact_file_cache.check_digest_obj_path(md5, 2)
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


def test_check_digest_obj_path_xxh128(artifact_file_cache):
    digest = xxh128_string("hi")
    path, exists, opener = artifact_file_cache.check_digest_obj_path(
        digest, 2, algorithm=ArtifactDigestAlgorithm.MANIFEST_XXH128
    )
    expected_path = os.path.join(
        artifact_file_cache._cache_dir,
        "obj",
        "xxh128",
        "7d",
        "596ce5fcabaf622a2300bbd7ea6e9a",
    )
    assert path == expected_path

    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert exists is False
    assert contents == "hi"


def test_check_digest_obj_path_override(artifact_file_cache):
    md5 = md5_string("hi")
    override_path = os.path.join(artifact_file_cache._cache_dir, "override.cache")
    path, exists, _ = artifact_file_cache.check_digest_obj_path(
        md5, 2, dest_path=override_path
    )
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
    path, exists, _ = artifact_file_cache.check_etag_obj_path(
        "http://my/url", "abc", 2, dest_path=override_path
    )
    assert path == override_path
    assert exists is False


def test_check_digest_obj_path_dest_path_ignores_existing_file(
    artifact_file_cache, tmp_path
):
    # The caller has already rejected the file at `dest_path`, so a same-size
    # file there must not be reported as a hit.
    dest_path = tmp_path / "file.txt"
    dest_path.write_text("jello")
    _, exists, _ = artifact_file_cache.check_digest_obj_path(
        md5_string("hello"), 5, dest_path=dest_path
    )
    assert exists is False


def test_check_etag_obj_path_dest_path_ignores_existing_file(
    artifact_file_cache, tmp_path
):
    dest_path = tmp_path / "file.txt"
    dest_path.write_text("jello")
    _, exists, _ = artifact_file_cache.check_etag_obj_path(
        "http://my/url", "abc", 5, dest_path=dest_path
    )
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
    file_1 = os.path.join(path_1, "aardvark")
    with open(file_1, "w") as f:
        f.truncate(5000)
        f.flush()
        os.fsync(f)

    path_2 = os.path.join(cache_root, "ab")
    os.makedirs(path_2)
    file_2 = os.path.join(path_2, "absolute")
    with open(file_2, "w") as f:
        f.truncate(2000)
        f.flush()
        os.fsync(f)

    path_3 = os.path.join(cache_root, "ac")
    os.makedirs(path_3)
    file_3 = os.path.join(path_3, "accelerate")
    with open(file_3, "w") as f:
        f.truncate(1000)
        f.flush()
        os.fsync(f)

    # Set explicit access times so cleanup order is deterministic.
    # On filesystems mounted with noatime, all files would otherwise
    # have the same atime, making the LRU sort order unpredictable.
    os.utime(file_1, (1000, 1000))  # oldest access → deleted first
    os.utime(file_2, (2000, 2000))
    os.utime(file_3, (3000, 3000))  # newest access → kept

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


def test_wandb_storage_policy_load_file_uses_cache_md5(artifact_file_cache, tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("hello")
    digest = "XUFAKrxLKna5cZ2REBfFkg=="

    path, _, opener = artifact_file_cache.check_digest_obj_path(digest=digest, size=5)
    with opener() as f:
        f.write("hello")

    policy = WandbStoragePolicy()
    entry = ArtifactManifestEntry(
        path=file,
        digest=digest,
        size=5,
    )

    # We need to pass an artifact, but this test doesn't actually use it
    empty_artifact = Artifact("test", type="dataset")

    local_path = policy.load_file(empty_artifact, entry)

    assert local_path == path


def test_wandb_storage_policy_load_file_uses_cache_xxh128(
    artifact_file_cache, tmp_path
):
    file = tmp_path / "file.txt"
    file.write_text("hello")
    digest = "tenBrQcbPn/Hec+qXlI4GA=="

    path, _, opener = artifact_file_cache.check_digest_obj_path(
        digest=digest, size=5, algorithm=ArtifactDigestAlgorithm.MANIFEST_XXH128
    )
    with opener() as f:
        f.write("hello")

    policy = WandbStoragePolicy()
    entry = ArtifactManifestEntry(
        path=file,
        digest=digest,
        size=5,
        extra={"alg": "XXH128"},
    )

    # We need to pass an artifact, but this test doesn't actually use it
    empty_artifact = Artifact("test", type="dataset", digest_algorithm="XXH128")

    local_path = policy.load_file(empty_artifact, entry)

    assert local_path == path


def test_wandb_storage_policy_load_file_skip_cache_override_does_not_leak(
    artifact_file_cache, tmp_path, mocker
):
    """A skip-cache load must not redirect a later load that uses the cache.

    Regression test for WB-33609: `load_file(dest_path=...)` stored the destination on
    the shared `ArtifactFileCache` and never cleared it, so the next
    `load_file(dest_path=None)` resolved to the previous skip-cache destination.
    """
    # Same size, different content: a stale override yields a wrong "cache hit".
    contents_a, contents_b = "hello", "world"
    digest_a, digest_b = md5_string(contents_a), md5_string(contents_b)

    # Artifact A is downloaded with `skip_cache=True` from a stubbed signed URL.
    dest_a = tmp_path / "download_a" / "file.txt"
    session = mocker.Mock()
    session.get.return_value.iter_content.return_value = [contents_a.encode()]

    # Artifact B is already in the cache, so loading it needs no network access.
    cache_path_b, _, opener = artifact_file_cache.check_digest_obj_path(
        digest=digest_b, size=len(contents_b)
    )
    with opener() as f:
        f.write(contents_b)

    policy = WandbStoragePolicy()
    policy._maybe_session = session
    artifact = Artifact("test", type="dataset")
    entry_a = ArtifactManifestEntry(path="file.txt", digest=digest_a, size=5)
    entry_a._download_url = "https://example.invalid/file_a"
    entry_b = ArtifactManifestEntry(path="file.txt", digest=digest_b, size=5)

    # `skip_cache=True`: `ArtifactManifestEntry.download` passes the destination.
    assert policy.load_file(artifact, entry_a, dest_path=str(dest_a)) == str(dest_a)
    assert dest_a.read_text() == contents_a

    # `skip_cache=False`: `ArtifactManifestEntry.download` passes `dest_path=None`.
    local_path_b = policy.load_file(artifact, entry_b, dest_path=None)

    assert local_path_b == cache_path_b
    assert dest_a.read_text() == contents_a


def test_wandb_storage_policy_load_reference_skip_cache_override_does_not_leak(
    artifact_file_cache, tmp_path
):
    """A skip-cache reference load must not redirect a later load that uses the cache.

    Regression test for WB-33609, via `load_reference` and `LocalFileHandler`.
    """
    # Same size, different content: a stale override yields a wrong "cache hit".
    contents_a, contents_b = "hello", "world"
    source_a = tmp_path / "source_a.txt"
    source_b = tmp_path / "source_b.txt"
    source_a.write_text(contents_a)
    source_b.write_text(contents_b)

    entry_a = ArtifactManifestEntry(
        path="file.txt",
        ref=source_a.as_uri(),
        digest=md5_string(contents_a),
        size=len(contents_a),
    )
    entry_b = ArtifactManifestEntry(
        path="file.txt",
        ref=source_b.as_uri(),
        digest=md5_string(contents_b),
        size=len(contents_b),
    )
    cache_path_b, _, _ = artifact_file_cache.check_digest_obj_path(
        digest=entry_b.digest, size=len(contents_b)
    )

    policy = WandbStoragePolicy()
    dest_a = tmp_path / "download_a" / "file.txt"

    # `skip_cache=True`: `ArtifactManifestEntry.download` passes the destination.
    local_path_a = policy.load_reference(entry_a, local=True, dest_path=str(dest_a))
    assert local_path_a == str(dest_a)
    assert dest_a.read_text() == contents_a

    # `skip_cache=False`: `ArtifactManifestEntry.download` passes `dest_path=None`.
    local_path_b = policy.load_reference(entry_b, local=True, dest_path=None)

    assert local_path_b == cache_path_b
    assert Path(local_path_b).read_text() == contents_b
    assert dest_a.read_text() == contents_a


def test_manifest_entry_download_skip_cache_replaces_stale_same_size_file(
    artifact_file_cache, tmp_path
):
    """`skip_cache=True` must re-download over a same-size file with wrong contents.

    The entry's checksum check rejects the stale file, and the skip-cache lookup
    must not then accept it again on size alone.
    """
    contents = "hello"
    source = tmp_path / "source.txt"
    source.write_text(contents)

    artifact = Artifact("test", type="dataset")
    entry = ArtifactManifestEntry(
        path="file.txt",
        ref=source.as_uri(),
        digest=md5_string(contents),
        size=len(contents),
    )
    entry._parent_artifact = artifact

    root = tmp_path / "root"
    dest_path = root / "file.txt"
    root.mkdir()
    dest_path.write_text("jello")

    local_path = entry.download(root=str(root), skip_cache=True)

    assert local_path == str(dest_path)
    assert dest_path.read_text() == contents


def test_local_file_handler_load_path_uses_cache(artifact_file_cache, tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("hello")
    uri = file.as_uri()
    digest = "XUFAKrxLKna5cZ2REBfFkg=="

    path, _, opener = artifact_file_cache.check_digest_obj_path(digest=digest, size=5)
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
    _, _, opener = artifact_file_cache.check_digest_obj_path(
        example_digest, size=10**30
    )

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

    _, _, opener = artifact_file_cache.check_digest_obj_path(
        digest=example_digest, size=7
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
    service_api = object()

    @property
    def client(self):
        return None

    def _artifact_from_id(self, _artifact_id: str) -> Artifact | None:
        artifact = wandb.Artifact("test", type="dataset")
        artifact.get_entry = lambda _: artifact
        artifact.ref_target = lambda: "wandb-artifact://deadbeef/path/to/file.json"
        artifact.download = lambda **kwargs: "foo/bar"
        return artifact


def test_wbartifact_handler_load_path_nonlocal():
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    manifest_entry = ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = WBArtifactHandler()
    handler._client = FakePublicApi()

    local_path = handler.load_path(manifest_entry)
    assert local_path == uri


def test_wbartifact_handler_load_path_local():
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    manifest_entry = ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = WBArtifactHandler()
    handler._client = FakePublicApi()

    local_path = handler.load_path(manifest_entry, local=True)
    assert local_path == path


def _make_wb_reference(
    tmp_path: Path, mocker
) -> tuple[WBArtifactHandler, ArtifactManifestEntry, Path, str]:
    """Return a handler, a `wandb-artifact://` entry, the dependency file, and its content.

    The dependency artifact holds one `file://` reference to a real file, and its
    default download root is kept inside `tmp_path`.
    """
    mocker.patch.dict(os.environ, {env.ARTIFACT_DIR: str(tmp_path / "artifacts")})

    contents = "hello"
    source = tmp_path / "source.txt"
    source.write_text(contents)

    dep_artifact = Artifact("dep", type="dataset")
    dep_entry = ArtifactManifestEntry(
        path="file.txt",
        ref=source.as_uri(),
        digest=md5_string(contents),
        size=len(contents),
    )
    dep_entry._parent_artifact = dep_artifact
    dep_artifact.get_entry = lambda _: dep_entry

    client = mocker.Mock()
    client._artifact_from_id.return_value = dep_artifact
    handler = WBArtifactHandler()
    handler._client = client

    entry = ArtifactManifestEntry(
        path="file.txt",
        ref="wandb-artifact://deadbeef/file.txt",
        digest=md5_string(contents),
        size=0,
    )
    dep_file = Path(dep_artifact._default_root()) / "file.txt"
    return handler, entry, dep_file, contents


def _cache_files(artifact_file_cache: ArtifactFileCache) -> list[Path]:
    return [p for p in artifact_file_cache._obj_dir.rglob("*") if p.is_file()]


def test_wbartifact_handler_load_path_dest_path(artifact_file_cache, tmp_path, mocker):
    handler, entry, dep_file, contents = _make_wb_reference(tmp_path, mocker)
    dest_path = tmp_path / "dest" / "file.txt"

    local_path = handler.load_path(entry, local=True, dest_path=str(dest_path))

    assert local_path == str(dest_path)
    assert dest_path.read_text() == contents
    # Nothing is staged in the dependency's download root or in the cache.
    assert not dep_file.exists()
    assert _cache_files(artifact_file_cache) == []


def test_wbartifact_handler_load_path_dest_path_replaces_stale_file(
    artifact_file_cache, tmp_path, mocker
):
    handler, entry, _, contents = _make_wb_reference(tmp_path, mocker)
    # A same-size file with the wrong contents at the destination is replaced.
    dest_path = tmp_path / "dest" / "file.txt"
    dest_path.parent.mkdir()
    dest_path.write_text("jello")

    local_path = handler.load_path(entry, local=True, dest_path=str(dest_path))

    assert local_path == str(dest_path)
    assert dest_path.read_text() == contents


def test_wbartifact_handler_load_path_dest_path_ignores_dependency_root(
    artifact_file_cache, tmp_path, mocker
):
    handler, entry, dep_file, contents = _make_wb_reference(tmp_path, mocker)
    # A same-size file with the wrong contents at the dependency's own download
    # root must be neither copied onward nor touched.
    dep_file.parent.mkdir(parents=True)
    dep_file.write_text("jello")
    dest_path = tmp_path / "dest" / "file.txt"

    local_path = handler.load_path(entry, local=True, dest_path=str(dest_path))

    assert local_path == str(dest_path)
    assert dest_path.read_text() == contents
    assert dep_file.read_text() == "jello"


def test_wbartifact_handler_load_path_dest_path_same_named_dependencies(
    artifact_file_cache, tmp_path, mocker
):
    """References to same-named artifacts from different projects do not collide.

    `Artifact._default_root()` is `<artifact dir>/<name>:<version>` with no project or
    entity, so two such dependencies share it. Loading into `dest_path` must not
    stage anything there.
    """
    mocker.patch.dict(os.environ, {env.ARTIFACT_DIR: str(tmp_path / "artifacts")})
    deps = {}
    for i, contents in enumerate(["hello", "world"]):
        source = tmp_path / f"source_{i}.txt"
        source.write_text(contents)
        dep_artifact = Artifact("model", type="dataset")
        dep_entry = ArtifactManifestEntry(
            path="weights.txt",
            ref=source.as_uri(),
            digest=md5_string(contents),
            size=len(contents),
        )
        dep_entry._parent_artifact = dep_artifact
        dep_artifact.get_entry = lambda _, e=dep_entry: e
        deps[f"deadbee{i}"] = dep_artifact
    roots = {dep._default_root() for dep in deps.values()}
    assert len(roots) == 1
    shared_root = Path(roots.pop())

    handler = WBArtifactHandler()
    handler._client = mocker.Mock()
    handler._client._artifact_from_id.side_effect = lambda b64_id: deps[
        b64_to_hex_id(b64_id)
    ]

    for i, contents in enumerate(["hello", "world"]):
        entry = ArtifactManifestEntry(
            path=f"project_{i}.txt",
            ref=f"wandb-artifact://deadbee{i}/weights.txt",
            digest=md5_string(contents),
            size=0,
        )
        dest_path = tmp_path / "dest" / f"project_{i}.txt"
        handler.load_path(entry, local=True, dest_path=str(dest_path))
        assert dest_path.read_text() == contents

    assert not shared_root.exists()


def test_wbartifact_handler_load_path_dest_path_replaces_symlink(
    artifact_file_cache, tmp_path, mocker
):
    handler, entry, _, contents = _make_wb_reference(tmp_path, mocker)
    # A symlink at the destination is replaced; its target is left alone.
    protected = tmp_path / "unrelated.txt"
    protected.write_text("precious user data")
    dest_path = tmp_path / "dest" / "file.txt"
    dest_path.parent.mkdir()
    dest_path.symlink_to(protected)

    local_path = handler.load_path(entry, local=True, dest_path=str(dest_path))

    assert local_path == str(dest_path)
    assert not dest_path.is_symlink()
    assert dest_path.read_text() == contents
    assert protected.read_text() == "precious user data"


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
