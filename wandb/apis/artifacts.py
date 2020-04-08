import base64
import collections
import hashlib
import json
import glob
import os
from six import string_types
import requests
import shutil
import tempfile
import time
import urllib

from wandb import InternalApi
from wandb.file_pusher import FilePusher
from wandb import util
from wandb.compat import tempfile as compat_tempfile

from wandb.apis import artifacts_cache

def md5_hash_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5

def md5_file_b64(path):
    return base64.b64encode(md5_hash_file(path).digest()).decode('ascii')

def md5_file_hex(path):
    return md5_hash_file(path).hexdigest()

def user_paths_to_path_specs(paths):
    # path_specs maps from internal artifact path to local path on disk
    path_specs = {}
    if paths is None:
        pass
    elif isinstance(paths, list):
        # every entry must be a file, and duplicate basenames are not allowed.
        # we don't check if they're valid files here. We'll do that later when we
        # checksum (so that we only have to do a big parallel operation in one place)
        for path in paths:
            basename = os.path.basename(path)
            if basename in path_specs:
                raise ValueError('Duplicate file name found in artifact file list. Pass a dictionary instead.')
            path_specs[basename] = path
    elif isinstance(paths, dict):
        # Cool
        path_specs = paths
    else:
        # We have a single file or directory
        # Note, we follow symlinks for files contained within the diretory
        path = paths
        if os.path.isdir(path):
            for dirpath, _, filenames in os.walk(path, followlinks=True):
                for fname in filenames:
                    local_path = os.path.join(dirpath, fname)
                    artifact_path = os.path.relpath(local_path, path)
                    path_specs[artifact_path] = local_path
        elif os.path.isfile(path):
            basename = os.path.basename(path)
            path_specs[basename] = path
        else:
            raise ValueError('paths must be a list, dictionary, or valid file or directory path.')
    return path_specs


class ArtifactManifestV1(object):
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
    
    """Used to keep track of local files in an artifact.
    
    Not yet implemented: save local manifests on the local filesystem, and implement
    smarter artifact downloads that are aware of locally cached files.
    """

    # A local manifest contains the path to the local file in addition to the path within
    # the artifact.
    LocalArtifactManifestEntry = collections.namedtuple('LocalArtifactManifestEntry', (
        'path', 'hash', 'local_path'))

    def __init__(self, paths):
        self._path_specs = user_paths_to_path_specs(paths)

        if len(self._path_specs) == 0:
            raise ValueError('Artifact must contain at least one file')

        self._local_entries = []
        for artifact_path, local_path in self._path_specs.items():
            self._local_entries.append(
                self.LocalArtifactManifestEntry(
                    artifact_path, md5_file_b64(local_path), os.path.abspath(local_path)))

        self._manifest = ArtifactManifestV1(self._local_entries)
        self._digest = self._manifest.digest

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


class LocalArtifact(object):
    def __init__(self, api, paths, digest, file_pusher=None, is_user_created=False):
        self._api = api
        self._file_pusher = file_pusher
        if self._file_pusher is None:
            self._file_pusher = FilePusher(self._api)
        self._is_user_created = is_user_created
        self._local_manifest = LocalArtifactManifestV1(paths)
        if digest != self._local_manifest.digest:
            # TODO: how to properly fail here?
            raise Error('Artifact digest doesn\'t match')
        self._server_artifact = None

    def save(self, name, metadata=None, description=None, aliases=None, labels=None):
        """Returns the server artifact."""
        artifact_type_id = self._api.create_artifact_type(name)
        self._server_artifact = self._api.create_artifact(
            artifact_type_id, self._local_manifest.digest,
            metadata=metadata,
            aliases=aliases, labels=labels, description=description,
            is_user_created=self._is_user_created)
        # TODO(artifacts):
        #   if it's committed, all is good. If it's committing, just moving ahead isn't necessarily
        #   correct. It may be better to poll until it's committed or failed, and then decided what to
        #   do
        if self._server_artifact['state'] == 'COMMITTED' or self._server_artifact['state'] == 'COMMITTING':
            # TODO: update aliases, labels, description etc?
            return self._server_artifact
        elif self._server_artifact['state'] != 'PENDING':
            # TODO: what to do in this case?
            raise Exception('Server artifact not in PENDING state', self._server_artifact)
        # TODO(artifacts)
        # if it is in PENDING but not created by us, we also have a problem (two parallel runs)
        # creating the same artifact. In theory this could be ok but the backend doesn't handle
        # it right now.
        for entry in self._local_manifest.entries:
            self._file_pusher.file_changed(entry.path, entry.local_path, self._server_artifact['id'])
        self._file_pusher.commit_artifact(self._server_artifact['id'])
        return self._server_artifact

    def commit(self):
        self._api.commit_artifact(self._server_artifact.id)

    def wait(self):
        if self._server_artifact is None:
            raise ValueError('Must call save first')
        while self._server_artifact.state != 'READY':
            time.sleep(2)


class LocalArtifactRead(object):
    def __init__(self, name, path):
        self._artifact_dir = None
        if path is not None:
            if not isinstance(path, string_types):
                raise ValueError("path must be a local file or directory")
            if os.path.isdir(path):
                self._artifact_dir = path
            elif os.path.isfile(path):
                self._artifact_dir = os.path.dirname(path)
            else:
                raise ValueError("path must be a local file or directory")
        self._local_manifest = LocalArtifactManifestV1(path)

    # TODO: give some way for the user to check if we have this on the server?

    @property
    def digest(self):
        return self._local_manifest.digest()

    def download(self, *args, **kwargs):
        return self._artifact_dir

class WriteableArtifact(object):
    """An artifact object you can write files into, and pass to log_artifact."""

    def __init__(self, type=None, description=None, metadata=None):
        self._cache = artifacts_cache.get_artifacts_cache()
        self.type = type
        self.description = description
        self.metadata = metadata
        self._write_dir = compat_tempfile.TemporaryDirectory(missing_ok_on_cleanup=True)

    @property
    def write_dir(self):
        return self._write_dir.name

    def finalize(self, digest):
        artifact_dir = self._cache.get_artifact_dir(self.type, digest)
        shutil.rmtree(artifact_dir)
        os.rename(self.write_dir, artifact_dir)
        return artifact_dir