import base64
import os
import random
import time
from multiprocessing import Pool

from wandb import wandb_sdk


def _cache_writer(cache_path):
    etag = "abcdef"
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache(cache_path)
    _, _, opener = cache.check_etag_obj_path(etag, 10)
    with opener() as f:
        f.write("".join(random.choice("0123456") for _ in range(10)))


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


def test_check_etag_obj_path():
    os.mkdir("cache")
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

    etag = "abcdef"
    path, exists, opener = cache.check_etag_obj_path(etag, 10)
    expected_path = os.path.join("cache", "obj", "etag", "ab", "cdef")
    with opener() as f:
        f.write("hi")
    with open(path) as f:
        contents = f.read()

    assert path == expected_path
    assert exists is False
    assert contents == "hi"


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
        path = os.path.join("cache", "obj", "etag", "ab")
        assert os.listdir(path) == ["cdef"]


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
