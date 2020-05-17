import os
import shutil

from wandb import util

class ArtifactsCache(object):
    def __init__(self, cache_dir):
        util.mkdir_exists_ok(cache_dir)
        self._cache_dir = cache_dir

    def get_artifact_dir(self, artifact_type, artifact_digest):
        dirname = os.path.join(self._cache_dir, 'final', artifact_type, artifact_digest, 'artifact')
        util.mkdir_exists_ok(dirname)
        return dirname

_artifacts_cache = None

def get_artifacts_cache():
    global _artifacts_cache
    if _artifacts_cache is None:
        # TODO: Load this from settings
        _artifacts_cache = ArtifactsCache(os.path.expanduser('~/.cache/wandb/artifacts'))
    return _artifacts_cache
