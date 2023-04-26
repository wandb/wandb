import asyncio
import base64
import os
import random
from multiprocessing import Pool
from urllib.parse import urlparse

import pytest
import wandb
from wandb.sdk import wandb_artifacts
from wandb.sdk.internal.artifact_saver import get_staging_dir


def test_opener_rejects_append_mode(cache):
    _, _, opener = cache.check_md5_obj_path(base64.b64encode(b"abcdef"), 10)

    with pytest.raises(ValueError):
        with opener("a"):
            pass

    # make sure that the ValueError goes away if we use a valid mode
    with opener("w"):
        pass


def test_check_md5_obj_path(cache):
    md5 = base64.b64encode(b"abcdef")
    path, exists, opener = cache.check_md5_obj_path(md5, 10)
    expected_path = os.path.join(cache._cache_dir, "obj", "md5", "61", "6263646566")
    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert path == expected_path
    assert exists is False
    assert contents == "hi"


def test_check_etag_obj_path_points_to_opener_dst(cache):
    path, _, opener = cache.check_etag_obj_path("http://my/url", "abc", 10)

    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert contents == "hi"


def test_check_etag_obj_path_returns_exists_if_exists(cache):
    size = 123
    _, exists, opener = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert not exists

    with opener() as f:
        f.write(size * "a")

    _, exists, _ = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert exists


def test_check_etag_obj_path_returns_not_exists_if_incomplete(cache):
    size = 123
    _, exists, opener = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert not exists

    with opener() as f:
        f.write((size - 1) * "a")

    _, exists, _ = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert not exists

    with opener() as f:
        f.write(size * "a")

    _, exists, _ = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert exists


def test_check_etag_obj_path_does_not_include_etag(cache):
    path, _, _ = cache.check_etag_obj_path("http://url/1", "abcdef", 10)
    assert "abcdef" not in path


@pytest.mark.parametrize(
    ["url1", "url2", "etag1", "etag2", "path_equal"],
    [
        ("http://url/1", "http://url/1", "abc", "abc", True),
        ("http://url/1", "http://url/1", "abc", "def", False),
        ("http://url/1", "http://url/2", "abc", "abc", False),
    ],
)
def test_check_etag_obj_path_hashes_url_and_etag(
    url1, url2, etag1, etag2, path_equal, cache
):
    path_1, _, _ = cache.check_etag_obj_path(url1, etag1, 10)
    path_2, _, _ = cache.check_etag_obj_path(url2, etag2, 10)

    if path_equal:
        assert path_1 == path_2
    else:
        assert path_1 != path_2


# This function should only be used in `test_check_write_parallel`,
# but it needs to be a global function for multiprocessing.
def _cache_writer(artifact_cache):
    etag = "abcdef"
    _, _, opener = artifact_cache.check_etag_obj_path("http://wandb.ex/foo", etag, 10)
    with opener() as f:
        f.write("".join(random.choice("0123456") for _ in range(10)))


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky")
def test_check_write_parallel(cache):
    num_parallel = 5

    p = Pool(num_parallel)
    p.map(_cache_writer, [cache for _ in range(num_parallel)])
    _cache_writer(cache)  # run in this process too for code coverage
    p.close()
    p.join()

    # Regardless of the ordering, we should be left with one file at the end.
    files = [f for f in (cache._cache_dir / "obj" / "etag").rglob("*") if f.is_file()]
    assert len(files) == 1


def test_artifacts_cache_cleanup_empty(cache):
    reclaimed_bytes = cache.cleanup(100000)
    assert reclaimed_bytes == 0


def test_artifacts_cache_cleanup(cache):
    cache_root = os.path.join(cache._cache_dir, "obj", "md5")

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

    reclaimed_bytes = cache.cleanup(5000)

    # We should get rid of "aardvark" in this case
    assert reclaimed_bytes == 5000


def test_artifacts_cache_cleanup_tmp_files(cache):
    path = os.path.join(cache._cache_dir, "obj", "md5", "aa")
    os.makedirs(path)
    with open(os.path.join(path, "tmp_abc"), "w") as f:
        f.truncate(1000)

    # Even if we are above our target size, the cleanup
    # should reclaim tmp files.
    reclaimed_bytes = cache.cleanup(10000)

    assert reclaimed_bytes == 1000


def test_local_file_handler_load_path_uses_cache(cache, tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("hello")
    uri = file.as_uri()
    digest = "XUFAKrxLKna5cZ2REBfFkg=="

    path, _, opener = cache.check_md5_obj_path(b64_md5=digest, size=123)
    with opener() as f:
        f.write(123 * "a")

    handler = wandb_artifacts.LocalFileHandler()
    handler._cache = cache

    local_path = handler.load_path(
        wandb_artifacts.ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=digest,
            size=123,
        ),
        local=True,
    )
    assert local_path == path


def test_s3_storage_handler_load_path_uses_cache(cache):
    uri = "s3://some-bucket/path/to/file.json"
    etag = "some etag"

    path, _, opener = cache.check_etag_obj_path(uri, etag, 123)
    with opener() as f:
        f.write(123 * "a")

    handler = wandb_artifacts.S3Handler()
    handler._cache = cache

    local_path = handler.load_path(
        wandb_artifacts.ArtifactManifestEntry(
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

    handler = wandb_artifacts.GCSHandler()
    local_path = handler.load_path(
        wandb_artifacts.ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=etag,
            size=123,
        ),
        # Default: local=False,
    )
    assert local_path == uri


def test_gcs_storage_handler_load_path_uses_cache(cache):
    uri = "gs://some-bucket/path/to/file.json"
    etag = "some etag"

    path, _, opener = cache.check_md5_obj_path(etag, 123)
    with opener() as f:
        f.write(123 * "a")

    handler = wandb_artifacts.GCSHandler()
    handler._cache = cache

    local_path = handler.load_path(
        wandb_artifacts.ArtifactManifestEntry(
            path="foo/bar",
            ref=uri,
            digest=etag,
            size=123,
        ),
        local=True,
    )
    assert local_path == path


def test_wbartifact_handler_load_path_nonlocal(monkeypatch):
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    artifact = wandb.Artifact("test", type="dataset")
    manifest_entry = wandb_artifacts.ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = wandb_artifacts.WBArtifactHandler()
    handler._client = lambda: None
    monkeypatch.setattr(wandb.apis.public.Artifact, "from_id", lambda _1, _2: artifact)
    artifact.get_path = lambda _: artifact
    artifact.ref_target = lambda: uri

    local_path = handler.load_path(manifest_entry)
    assert local_path == uri


def test_wbartifact_handler_load_path_local(monkeypatch):
    path = "foo/bar"
    uri = "wandb-artifact://deadbeef/path/to/file.json"
    artifact = wandb.Artifact("test", type="dataset")
    manifest_entry = wandb_artifacts.ArtifactManifestEntry(
        path=path,
        ref=uri,
        digest="XUFAKrxLKna5cZ2REBfFkg==",
        size=123,
    )

    handler = wandb_artifacts.WBArtifactHandler()
    handler._client = lambda: None
    monkeypatch.setattr(wandb.apis.public.Artifact, "from_id", lambda _1, _2: artifact)
    artifact.get_path = lambda _: artifact
    artifact.download = lambda: path

    local_path = handler.load_path(manifest_entry, local=True)
    assert local_path == path


def test_storage_policy_incomplete():
    class UnfinishedStoragePolicy(wandb_artifacts.StoragePolicy):
        pass

    # Invalid argument values since we're only testing abstract code coverage.
    abstract_method_args = {
        "name": {},
        "from_config": dict(config={}),
        "config": {},
        "load_file": dict(artifact=None, manifest_entry=None),
        "store_file_sync": dict(
            artifact_id="", artifact_manifest_id="", entry=None, preparer=None
        ),
        "store_reference": dict(artifact=None, path=""),
        "load_reference": dict(manifest_entry=None),
    }
    usp = UnfinishedStoragePolicy()
    for method, kwargs in abstract_method_args.items():
        with pytest.raises(NotImplementedError):
            getattr(usp, method)(**kwargs)

    async_method_args = {
        "store_file_async": dict(
            artifact_id="", artifact_manifest_id="", entry=None, preparer=None
        )
    }
    for method, kwargs in async_method_args.items():
        with pytest.raises(NotImplementedError):
            asyncio.new_event_loop().run_until_complete(getattr(usp, method)(**kwargs))

    UnfinishedStoragePolicy.name = lambda: "UnfinishedStoragePolicy"

    policy = wandb_artifacts.StoragePolicy.lookup_by_name("UnfinishedStoragePolicy")
    assert policy is UnfinishedStoragePolicy

    not_policy = wandb_artifacts.StoragePolicy.lookup_by_name("NotAStoragePolicy")
    assert not_policy is None


def test_storage_handler_incomplete():
    class UnfinishedStorageHandler(wandb_artifacts.StorageHandler):
        pass

    ush = UnfinishedStorageHandler()

    with pytest.raises(NotImplementedError):
        ush.can_handle(parsed_url=urlparse("https://wandb.com"))
    with pytest.raises(NotImplementedError):
        ush.load_path(manifest_entry=None)
    with pytest.raises(NotImplementedError):
        ush.store_path(artifact=None, path="")


def test_unwritable_staging_dir(monkeypatch):
    # Use a non-writable directory as the staging directory.
    # CI just doesn't care about permissions, so we're patching os.makedirs 🙃
    def nope(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "makedirs", nope)

    with pytest.raises(PermissionError, match="WANDB_DATA_DIR"):
        _ = get_staging_dir()
