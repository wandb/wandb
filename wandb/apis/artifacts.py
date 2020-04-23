import collections
import json
import requests
import tempfile

from wandb.compat import tempfile as compat_tempfile

from wandb.apis import artifacts_cache
from wandb.apis.artifacts_storage import *


class ServerManifestV1(object):
    """This implements the same artifact digest algorithm as the server."""

    # hash must be the base64 encoded md5 checksum of the file at path.
    ArtifactManifestEntry = collections.namedtuple('ArtifactManifestEntry', ('path', 'hash'))

    def __init__(self, entries):
        # lexicographic sort. paths must be unique, so sort doesn't ever visit hash
        self._entries = sorted(entries)

    def dump(self, fp):
        fp.write('wandb-artifact-manifest-v1\n')
        for entry in self._entries:
            fp.write('%s %s\n' % (requests.utils.quote(entry.path), entry.hash))

    @property
    def digest(self):
        with tempfile.NamedTemporaryFile('w+') as fp:
            self.dump(fp)
            fp.seek(0)
            return md5_file_hex(fp.name)


class LocalArtifactManifestV1(object):
    
    """Used to keep track of local files in an artifact."""

    # A local manifest contains the path to the local file in addition to the path within
    # the artifact.
    LocalArtifactManifestEntry = collections.namedtuple('LocalArtifactManifestEntry', (
        'path', 'hash', 'local_path'))

    def __init__(self, paths):
        # TODO: passing this local manifest instance as the artifact is not what we want.
        self._file_specs = {}

        def add_file_spec(name, path):
            self._file_specs[name] = path

        storage_policy = WandbStoragePolicy(self, add_file_spec)
        # storage_policy = TrackingPolicy(self)
        manifest = ArtifactManifestV1(self, storage_policy)
        manifest.store_paths(paths)

        # Add the manifest itself as a file
        with tempfile.NamedTemporaryFile('w+', suffix=".json", delete=False) as fp:
            json.dump(manifest.to_manifest_json(), fp, indent=4)
            self._file_specs['wandb_manifest.json'] = fp.name

        self._local_entries = []
        for artifact_path, local_path in self._file_specs.items():
            self._local_entries.append(
                self.LocalArtifactManifestEntry(
                    artifact_path, md5_file_b64(local_path), os.path.abspath(local_path)))

        self._manifest = ServerManifestV1(self._local_entries)
        self._digest = self._manifest.digest

    def move(self, from_dir, to_dir):
        self._local_entries = [
            self.LocalArtifactManifestEntry(
                e.path,
                e.hash,
                os.path.join(to_dir, os.path.relpath(e.local_path, from_dir)))
            for e in self._local_entries
        ]

    @property
    def entries(self):
        return self._local_entries

    @property
    def digest(self):
        return self._digest

    def dump(self, fp):
        # TODO(artifacts): finalize format
        fp.write('version: 1\n')
        fp.write('digest: %s\n' % self._digest)
        for entry in self._local_entries:
            fp.write('%s %s %s\n' % (entry.path, entry.local_path, entry.hash))


class WriteableArtifact(object):
    """An artifact object you can write files into, and pass to log_artifact."""

    def __init__(self, type=None, description=None, metadata=None):
        self._cache = artifacts_cache.get_artifacts_cache()
        self.type = type
        self.description = description
        self.metadata = metadata
        self._artifact_dir = compat_tempfile.TemporaryDirectory(missing_ok_on_cleanup=True)
        self._external_data_dir = compat_tempfile.TemporaryDirectory(missing_ok_on_cleanup=True)

    @property
    def manifest(self):
        return LocalArtifactManifestV1(self.artifact_dir)

    @property
    def digest(self):
        return self.manifest.digest

    @property
    def artifact_dir(self):
        return self._artifact_dir.name

    @property
    def external_data_dir(self):
        return self._external_data_dir.name
