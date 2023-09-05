"""Benchmark the time it takes to clear the cache.

Clearing the cache is an expensive operation that can cause a system to hang for a bit.
This script tries to quantify that.

On my M1 Max Macbook Pro 10,000 files of size 4KB takes about 0.7 seconds to clear (as
of Aug 23, 2023).
"""

from functools import partial
from secrets import token_bytes

import pytest
from wandb.sdk.artifacts.artifacts_cache import ArtifactsCache
from wandb.sdk.lib.hashutil import _b64_from_hasher, _md5


def add_files(cache, num_files, file_size):
    for _ in range(num_files):
        tag = token_bytes(16)
        content = tag + b"\0" * (file_size - 16)
        content = content[:file_size]
        b64_hash = _b64_from_hasher(_md5(content))

        _, _, opener = cache.check_md5_obj_path(b64_hash, file_size)
        with opener(mode="wb") as f:
            f.write(tag)
            f.truncate(file_size)


@pytest.mark.parametrize("num_files", [10, 100, 1000, 10000])
def test_benchmark_cache_cleanup(tmp_path, benchmark, num_files):
    cache = ArtifactsCache(tmp_path / "cache")

    create_anew = partial(add_files, cache=cache, num_files=num_files, file_size=4096)
    clear = partial(cache.cleanup, target_size=0)

    benchmark.pedantic(clear, setup=create_anew, warmup_rounds=1, rounds=5)
