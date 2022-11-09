import base64
import os
import pathlib
import random
import time
from multiprocessing import Pool

import pytest
from wandb import wandb_sdk


# This function should only be used in `test_check_write_parallel`,
# but it needs to be a global function for multiprocessing.
def _cache_writer(cache_path):
    etag = "abcdef"
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache(cache_path)
    _, _, opener = cache.check_etag_obj_path("http://wandb.example/foo", etag, 10)
    with opener() as f:
        f.write("".join(random.choice("0123456") for _ in range(10)))


def test_opener_rejects_append_mode():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
    path, exists, opener = cache.check_md5_obj_path(base64.b64encode(b"abcdef"), 10)

    with pytest.raises(ValueError):
        with opener("a"):
            pass

    # make sure that the ValueError goes away if we use a valid mode
    with opener("w"):
        pass


def test_check_md5_obj_path():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    md5 = base64.b64encode(b"abcdef")
    path, exists, opener = cache.check_md5_obj_path(md5, 10)
    expected_path = os.path.join("cache", "obj", "md5", "61", "6263646566")
    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert path == expected_path
    assert exists is False
    assert contents == "hi"


def test_check_etag_obj_path_points_to_opener_dst():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    path, exists, opener = cache.check_etag_obj_path("http://my/url", "abc", 10)

    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert contents == "hi"


def test_check_etag_obj_path_returns_exists_if_exists():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    size = 123
    _, exists, opener = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert not exists

    with opener() as f:
        f.write(size * "a")

    _, exists, _ = cache.check_etag_obj_path("http://my/url", "abc", size)
    assert exists


def test_check_etag_obj_path_returns_not_exists_if_incomplete():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

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


def test_check_etag_obj_path_does_not_include_etag():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

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
def test_check_etag_obj_path_hashes_url_and_etag(url1, url2, etag1, etag2, path_equal):
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    path_1, _, _ = cache.check_etag_obj_path(url1, etag1, 10)
    path_2, _, _ = cache.check_etag_obj_path(url2, etag2, 10)

    if path_equal:
        assert path_1 == path_2
    else:
        assert path_1 != path_2


def test_check_write_parallel(runner):
    with runner.isolated_filesystem() as t:
        cache = os.path.join(t, "cache")
        num_parallel = 5

        p = Pool(num_parallel)
        p.map(_cache_writer, [cache for _ in range(num_parallel)])
        _cache_writer(cache)  # run in this process too for code coverage
        p.close()
        p.join()

        # Regardless of the ordering, we should be left with one
        # file at the end.
        files = [
            f for f in (pathlib.Path(cache) / "obj" / "etag").rglob("*") if f.is_file()
        ]
        assert len(files) == 1


def test_artifacts_cache_cleanup_empty():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
    reclaimed_bytes = cache.cleanup(100000)
    assert reclaimed_bytes == 0


def test_artifacts_cache_cleanup():
    cache_root = os.path.join("cache", "obj", "md5")

    path_1 = os.path.join(cache_root, "aa")
    os.makedirs(path_1)
    with open(os.path.join(path_1, "aardvark"), "w") as f:
        f.truncate(5000)
    time.sleep(0.1)

    path_2 = os.path.join(cache_root, "ab")
    os.makedirs(path_2)
    with open(os.path.join(path_2, "absolute"), "w") as f:
        f.truncate(2000)
    time.sleep(0.1)

    path_3 = os.path.join(cache_root, "ac")
    os.makedirs(path_3)
    with open(os.path.join(path_3, "accelerate"), "w") as f:
        f.truncate(1000)

    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
    reclaimed_bytes = cache.cleanup(5000)

    # We should get rid of "aardvark" in this case
    assert reclaimed_bytes == 5000


def test_artifacts_cache_cleanup_tmp_files():
    path = os.path.join("cache", "obj", "md5", "aa")
    os.makedirs(path)
    with open(os.path.join(path, "tmp_abc"), "w") as f:
        f.truncate(1000)

    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    # Even if we are above our target size, the cleanup
    # should reclaim tmp files.
    reclaimed_bytes = cache.cleanup(10000)

    assert reclaimed_bytes == 1000
