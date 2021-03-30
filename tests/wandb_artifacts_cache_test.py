import os
import base64
import time
import random
from multiprocessing import Pool

from wandb import wandb_sdk


def _cache_writer(cache_path):
    etag = "abcdef"
    cache = wandb_sdk.wandb_artifacts.ArtifactsCache(cache_path)
    _, _, opener = cache.check_etag_obj_path(etag, 10)
    with opener() as f:
        f.write("".join(random.choice("0123456") for _ in range(10)))


def test_check_md5_obj_path(runner):
    with runner.isolated_filesystem():
        os.mkdir("cache")
        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

        md5 = base64.b64encode("abcdef".encode("ascii"))
        path, exists, opener = cache.check_md5_obj_path(md5, 10)
        with opener() as f:
            f.write("hi")
        with open(path) as f:
            contents = f.read()

        assert path == "cache/obj/md5/61/6263646566"
        assert exists is False
        assert contents == "hi"


def test_check_etag_obj_path(runner):
    with runner.isolated_filesystem():
        os.mkdir("cache")
        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

        etag = "abcdef"
        path, exists, opener = cache.check_etag_obj_path(etag, 10)
        with opener() as f:
            f.write("hi")
        with open(path) as f:
            contents = f.read()

        assert path == "cache/obj/etag/ab/cdef"
        assert exists is False
        assert contents == "hi"


def test_check_write_parallel(runner):
    with runner.isolated_filesystem() as t:
        cache = os.path.join(t, "cache")
        print(cache)
        num_parallel = 5
        with Pool(num_parallel) as p:
            p.map(_cache_writer, [cache for _ in range(num_parallel)])

        # Regardless of the ordering, we should be left with one
        # file at the end.
        assert os.listdir("cache/obj/etag/ab") == ["cdef"]


def test_artifacts_cache_cleanup_empty(runner):
    with runner.isolated_filesystem():
        os.mkdir("cache")
        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
        reclaimed_bytes = cache.cleanup(100000)
        assert reclaimed_bytes == 0


def test_artifacts_cache_cleanup(runner):
    with runner.isolated_filesystem():
        os.makedirs("cache/obj/md5/aa/")
        with open("cache/obj/md5/aa/aardvark", "w") as f:
            f.truncate(5000)
        time.sleep(0.1)

        os.makedirs("cache/obj/md5/ab/")
        with open("cache/obj/md5/ab/absolute", "w") as f:
            f.truncate(2000)
        time.sleep(0.1)

        os.makedirs("cache/obj/md5/ac/")
        with open("cache/obj/md5/ac/accelerate", "w") as f:
            f.truncate(1000)

        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
        reclaimed_bytes = cache.cleanup(5000)

        # We should get rid of "aardvark" in this case
        assert reclaimed_bytes == 5000


def test_artifacts_cache_cleanup_tmp_files(runner):
    with runner.isolated_filesystem():
        os.makedirs("cache/obj/md5/aa/")
        with open("cache/obj/md5/aa/tmp_abc", "w") as f:
            f.truncate(1000)

        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")

        # Even if we are above our target size, the cleanup
        # should reclaim tmp files.
        reclaimed_bytes = cache.cleanup(10000)

        assert reclaimed_bytes == 1000
