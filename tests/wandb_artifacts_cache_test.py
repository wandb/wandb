import os

from wandb import wandb_sdk


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

        os.makedirs("cache/obj/md5/ab/")
        with open("cache/obj/md5/ab/absolute", "w") as f:
            f.truncate(2000)

        os.makedirs("cache/obj/md5/ac/")
        with open("cache/obj/md5/ac/accelerate", "w") as f:
            f.truncate(1000)

        cache = wandb_sdk.wandb_artifacts.ArtifactsCache("cache")
        reclaimed_bytes = cache.cleanup(5000)

        # We should get rid of "aardvark" in this case
        assert reclaimed_bytes == 5000
