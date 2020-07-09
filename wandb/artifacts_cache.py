import base64
import os
import shutil

from wandb import env
from wandb import util

class ArtifactsCache(object):
    def __init__(self, cache_dir):
        self._cache_dir = cache_dir
        util.mkdir_exists_ok(self._cache_dir)
        self._md5_obj_dir = os.path.join(self._cache_dir, 'obj', 'md5')
        self._etag_obj_dir = os.path.join(self._cache_dir, 'obj', 'etag')

    def check_md5_obj_path(self, b64_md5, size):
        hex_md5 = util.bytes_to_hex(base64.b64decode(b64_md5))
        path = os.path.join(self._cache_dir, 'obj', 'md5', hex_md5[:2], hex_md5[2:])
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False

    def check_etag_obj_path(self, etag, size):
        path = os.path.join(self._cache_dir, 'obj', 'etag', etag[:2], etag[2:])
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False

_artifacts_cache = None

def get_artifacts_cache():
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), 'artifacts')
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache
