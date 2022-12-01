import contextlib
import hashlib
import os
import random
import sys
from typing import IO, ContextManager, Dict, Tuple

import wandb
from wandb import env, hashutil, util

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol


class Opener(Protocol):
    def __call__(self, mode: str = ...) -> ContextManager[IO]:
        pass


class ArtifactsCache:

    _TMP_PREFIX = "tmp"

    def __init__(self, cache_dir):
        self._cache_dir = cache_dir
        util.mkdir_exists_ok(self._cache_dir)
        self._md5_obj_dir = os.path.join(self._cache_dir, "obj", "md5")
        self._etag_obj_dir = os.path.join(self._cache_dir, "obj", "etag")
        self._artifacts_by_id = {}
        self._random = random.Random()
        self._random.seed()
        self._artifacts_by_client_id = {}

    def check_md5_obj_path(
        self, b64_md5: hashutil.B64MD5, size: int
    ) -> Tuple[util.FilePathStr, bool, "Opener"]:
        hex_md5 = hashutil.b64_string_to_hex(b64_md5)
        path = os.path.join(self._cache_dir, "obj", "md5", hex_md5[:2], hex_md5[2:])
        opener = self._cache_opener(path)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True, opener
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False, opener

    # TODO(spencerpearson): this method at least needs its signature changed.
    # An ETag is not (necessarily) a checksum.
    def check_etag_obj_path(
        self,
        url: util.URIStr,
        etag: hashutil.ETag,
        size: int,
    ) -> Tuple[util.FilePathStr, bool, "Opener"]:
        hexhash = hashlib.sha256(
            hashlib.sha256(url.encode("utf-8")).digest()
            + hashlib.sha256(etag.encode("utf-8")).digest()
        ).hexdigest()
        path = os.path.join(self._cache_dir, "obj", "etag", hexhash[:2], hexhash[2:])
        opener = self._cache_opener(path)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True, opener
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False, opener

    def get_artifact(self, artifact_id):
        return self._artifacts_by_id.get(artifact_id)

    def store_artifact(self, artifact):
        self._artifacts_by_id[artifact.id] = artifact

    def get_client_artifact(self, client_id):
        return self._artifacts_by_client_id.get(client_id)

    def store_client_artifact(self, artifact):
        self._artifacts_by_client_id[artifact._client_id] = artifact

    def cleanup(self, target_size: int) -> int:
        bytes_reclaimed: int = 0
        paths: Dict[os.PathLike, os.stat_result] = {}
        total_size: int = 0
        for root, _, files in os.walk(self._cache_dir):
            for file in files:
                path = os.path.join(root, file)
                stat = os.stat(path)

                if file.startswith(ArtifactsCache._TMP_PREFIX):
                    try:
                        os.remove(path)
                        bytes_reclaimed += stat.st_size
                    except OSError:
                        pass
                    continue

                paths[path] = stat
                total_size += stat.st_size

        sorted_paths = sorted(paths.items(), key=lambda x: x[1].st_atime)
        for path, stat in sorted_paths:
            if total_size < target_size:
                return bytes_reclaimed

            try:
                os.remove(path)
            except OSError:
                pass

            total_size -= stat.st_size
            bytes_reclaimed += stat.st_size
        return bytes_reclaimed

    def _cache_opener(self, path):
        @contextlib.contextmanager
        def helper(mode="w"):

            if "a" in mode:
                raise ValueError("Appending to cache files is not supported")

            dirname = os.path.dirname(path)
            tmp_file = os.path.join(
                dirname,
                "%s_%s"
                % (
                    ArtifactsCache._TMP_PREFIX,
                    util.rand_alphanumeric(length=8, rand=self._random),
                ),
            )
            with util.fsync_open(tmp_file, mode=mode) as f:
                yield f

            try:
                # Use replace where we can, as it implements an atomic
                # move on most platforms. If it doesn't exist, we have
                # to use rename which isn't atomic in all cases but there
                # isn't a better option.
                #
                # The atomic replace is important in the event multiple processes
                # attempt to write to / read from the cache at the same time. Each
                # writer firsts stages its writes to a temporary file in the cache.
                # Once it is finished, we issue an atomic replace operation to update
                # the cache. Although this can result in redundant downloads, this
                # guarantees that readers can NEVER read incomplete files from the
                # cache.
                #
                # IMPORTANT: Replace is NOT atomic across different filesystems. This why
                # it is critical that the temporary files sit directly in the cache --
                # they need to be on the same filesystem!
                os.replace(tmp_file, path)
            except AttributeError:
                os.rename(tmp_file, path)

        return helper


_artifacts_cache = None


def get_artifacts_cache() -> ArtifactsCache:
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), "artifacts")
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache
