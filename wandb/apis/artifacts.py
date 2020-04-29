import collections
import json
import base64
import hashlib
import os
import sys
import requests
import tempfile
import shutil
from abc import ABC, abstractmethod
from six.moves.urllib.parse import urlparse

from wandb.compat import tempfile as compat_tempfile

from wandb.apis import artifacts_cache
from wandb import util


def md5_string(string):
    hash_md5 = hashlib.md5()
    hash_md5.update(string.encode())
    return base64.b64encode(hash_md5.digest()).decode('ascii')


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


class LocalArtifact(object):
    """An artifact object you can write files into, and pass to log_artifact."""

    # A local manifest contains the path to the local file in addition to the path within
    # the artifact.
    LocalArtifactManifestEntry = collections.namedtuple('LocalArtifactManifestEntry', (
        'path', 'hash', 'local_path'))

    def __init__(self, save_callback, type, name, description=None, metadata=None, labels=None,
                 aliases=None, storage_policy=None):
        self._file_specs = {}
        self._final = False

        def add_file_spec(name, path):
            self._file_specs[name] = path

        storage_policy = storage_policy or WandbStoragePolicy(add_file_spec)
        self._save_callback = save_callback
        self._digest = None
        self._file_entries = None
        self._manifest = ArtifactManifestV1(self, storage_policy)
        self._cache = artifacts_cache.get_artifacts_cache()
        self._artifact_dir = compat_tempfile.TemporaryDirectory(missing_ok_on_cleanup=True)
        self._new_files = []
        self.type = type
        self.name = name
        self.description = description
        self.metadata = metadata
        self.labels = labels
        self.aliases = aliases

    @property
    def id(self):
        # The artifact hasn't been saved so an ID doesn't exist yet.
        return None

    @property
    def manifest(self):
        self.finalize()
        return self._manifest

    @property
    def digest(self):
        self.finalize()
        # Digest will be none if the artifact hasn't been saved yet.
        return self._digest

    def add_file(self, path, name=None):
        if self._final:
            raise ValueError('Can\'t add to finalized artifact.')
        self._manifest.store_path(path, name=name)

    def add_reference(self, path, name=None):
        if self._final:
            raise ValueError('Can\'t add to finalized artifact.')
        self._manifest.store_path(path, name=name, reference=True)

    def new_file(self, name):
        if self._final:
            raise ValueError('Can\'t add to finalized artifact.')
        path = os.path.join(self._artifact_dir.name, name)
        if os.path.exists(path):
            raise ValueError('File with name "%s" already exists' % name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._new_files.append((name, path))
        return open(path, 'w')

    def load_path(self, name, expand_dirs=False):
        raise ValueError('Cannot load paths from an artifact before it has been saved')

    def finalize(self):
        if self._final:
            return self._file_entries
        self._final = True

        # Record any created files in the manifest.
        for (name, path) in self._new_files:
            self._manifest.store_path(path, name=name)

        # Add the manifest itself as a file.
        with tempfile.NamedTemporaryFile('w+', suffix=".json", delete=False) as fp:
            json.dump(self._manifest.to_manifest_json(), fp, indent=4)
            self._file_specs['wandb_manifest.json'] = fp.name

        file_entries = []
        for artifact_path, local_path in self._file_specs.items():
            file_entries.append(self.LocalArtifactManifestEntry(
                artifact_path, md5_file_b64(local_path), os.path.abspath(local_path)))

        # Calculate the server manifest
        server_manifest = ServerManifestV1(file_entries)
        self._digest = server_manifest.digest

        # If there are new files, move them into the artifact cache.
        # TODO: careful with the download logic to make sure it still knows when to download files
        if len(self._new_files) > 0:
            final_artifact_dir = self._cache.get_artifact_dir(self.type, server_manifest.digest)
            shutil.rmtree(final_artifact_dir)
            os.rename(self._artifact_dir.name, final_artifact_dir)

            # Update the file entries for new files to point at their new location.
            def remap_file_entry(file_entry):
                if not file_entry.local_path.startswith(self._artifact_dir.name):
                    return file_entry
                rel_path = os.path.relpath(file_entry.local_path, start=self._artifact_dir.name)
                local_path = os.path.join(final_artifact_dir, rel_path)
                return self.LocalArtifactManifestEntry(
                    file_entry.path, file_entry.hash, local_path)

            file_entries = [remap_file_entry(file_entry) for file_entry in file_entries]

        self._file_entries = file_entries
        return self._file_entries

    def save(self):
        file_entries = self.finalize()
        self._save_callback(self, file_entries)


class ArtifactManifest(ABC):

    @classmethod
    @abstractmethod
    def from_manifest_json(cls, artifact, manifest_json):
        if 'version' not in manifest_json:
            raise ValueError('Invalid manifest format. Must contain version field.')
        version = manifest_json['version']
        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(artifact, manifest_json)

    @classmethod
    @abstractmethod
    def version(cls):
        pass

    def __init__(self, artifact, storage_policy, entries=None):
        self.artifact = artifact
        self.storage_policy = storage_policy
        self.entries = entries or {}

    @abstractmethod
    def to_manifest_json(self):
        raise NotImplementedError()

    def load_path(self, path, local=False, expand_dirs=False):
        if path in self.entries:
            return self.storage_policy.load_path(self.artifact, self.entries[path], local=local)

        # the path could be a dictionary, so load all matching prefixes
        paths = []
        for (name, entry) in self.entries.items():
            if name.startswith(path):
                paths.append(self.storage_policy.load_path(self.artifact, entry, local=local))

        if len(paths) > 0 and local:
            return os.path.join(self.artifact.artifact_dir, path)
        if len(paths) > 0 and not local:
            if expand_dirs:
                return paths
            raise ValueError('Cannot fetch remote path of directory "%s". '
                             'Set expand_dirs=True get remote paths for directories.' % path)
        raise ValueError('Failed to find "%s" in artifact manifest' % path)

    def store_path(self, path, name=None, reference=False):
        for entry in self.storage_policy.store_path(self.artifact, path, name=name, reference=reference):
            self.entries[entry.name] = entry


class ArtifactManifestV1(ArtifactManifest):

    @classmethod
    def version(cls):
        return 1

    @classmethod
    def from_manifest_json(cls, artifact, manifest_json):
        if manifest_json['version'] != cls.version():
            raise ValueError('Expected manifest version 1, got %s' % manifest_json['version'])

        storage_policy_name = manifest_json['storagePolicy']
        storage_policy_config = manifest_json.get('storagePolicyConfig', {})
        storage_policy_cls = StoragePolicy.lookup_by_name(storage_policy_name)
        if storage_policy_cls is None:
            raise ValueError('Failed to find storage policy "%s"' % storage_policy_name)

        entries = {
            name: ArtifactManifestEntry(name, val['path'], val['md5'], val['extra'])
            for name, val in manifest_json['contents'].items()
        }

        return cls(artifact, storage_policy_cls.from_config(storage_policy_config), entries)

    def __init__(self, artifact, storage_policy, entries=None):
        super(ArtifactManifestV1, self).__init__(artifact, storage_policy, entries=entries)

    def to_manifest_json(self):
        return {
            'version': self.__class__.version(),
            'storagePolicy': self.storage_policy.name(),
            'storagePolicyConfig': self.storage_policy.config() or {},
            'contents': {
                entry.name: {
                    'md5': entry.md5,
                    'path': entry.path,
                    'extra': entry.extra,
                } for entry in sorted(self.entries.values(), key=lambda k: k.name)
            }
        }


class ArtifactManifestEntry(object):

    def __init__(self, name, path, md5, extra=None):
        self.name = name
        self.path = path
        self.md5 = md5
        self.extra = extra


class StoragePolicy(ABC):

    @classmethod
    def lookup_by_name(cls, name):
        for sub in cls.__subclasses__():
            if sub.name() == name:
                return sub
        return None

    @classmethod
    @abstractmethod
    def name(cls):
        pass

    @classmethod
    @abstractmethod
    def from_config(cls, config):
        pass

    @abstractmethod
    def config(self):
        pass

    @abstractmethod
    def load_path(self, artifact, manifest_entry, local=False):
        pass

    @abstractmethod
    def store_path(self, artifact, path, name=None, reference=False):
        pass


def wandb_policy(upload_callback):
    def create(artifact):
        return WandbStoragePolicy(artifact, upload_callback)
    return create


class WandbStoragePolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-storage-policy-v1'

    @classmethod
    def from_config(cls, config):
        def upload_callback(name, path):
            # Not valid to upload from here.
            raise NotImplementedError()

        return cls(upload_callback)

    def __init__(self, wandb_upload_callback):
        wandb = WandbFileHandler(wandb_upload_callback)
        local = LocalFileHandler(upload_callback=wandb.upload_callback)

        self._handler = MultiHandler(handlers=[
            wandb,
            local,
        ], default_handler=TrackingHandler())

    def config(self):
        return None

    def load_path(self, artifact, manifest_entry, local=False):
        return self._handler.load_path(artifact, manifest_entry, local=local)

    def store_path(self, artifact, path, name=None, reference=False):
        return self._handler.store_path(artifact, path, name=name, reference=reference)


class S3BucketPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-s3-bucket-policy-v1'

    @classmethod
    def from_config(cls, config):
        if 'bucket' not in config:
            raise ValueError('Bucket name not found in config')
        return cls(config['bucket'])

    def __init__(self, bucket):
        self._bucket = bucket
        s3 = S3Handler(bucket)
        local = LocalFileHandler(upload_callback=s3.upload_callback)

        self._handler = MultiHandler(handlers=[
            s3,
            local,
        ], default_handler=TrackingHandler())

    def config(self):
        return {
            'bucket': self._bucket
        }

    def load_path(self, artifact, manifest_entry, local=False):
        return self._handler.load_path(artifact, manifest_entry, local=local)

    def store_path(self, artifact, path, name=None, reference=False):
        return self._handler.store_path(artifact, path, name=name, reference=reference)


class TrackingPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-tracking-policy-v1'

    @classmethod
    def from_config(cls, config):
        return cls()

    def __init__(self):
        self._handler = MultiHandler(default_handler=TrackingHandler())

    def config(self):
        return None

    def load_path(self, artifact, manifest_entry, local=False):
        return self._handler.load_path(artifact, manifest_entry, local=local)

    def store_path(self, artifact, path, name=None, reference=False):
        return self._handler.store_path(artifact, path, name=name, reference=reference)


class StorageHandler(ABC):

    @abstractmethod
    def scheme(self):
        """
        :return: The scheme to which this handler applies.
        :rtype: str
        """
        pass

    @abstractmethod
    def load_path(self, artifact, manifest_entry, remote=False):
        """
        Loads the file or directory within the specified artifact given its
        corresponding index entry.

        :param manifest_entry: The index entry to load
        :type manifest_entry: ArtifactManifestEntry
        :return: A path to the file represented by `index_entry`
        :rtype: os.PathLike
        """
        pass

    @abstractmethod
    def store_path(self, artifact, path, name=None, reference=False):
        """
        Stores the file or directory at the given path within the specified artifact.

        :param path: The path to store
        :type path: str
        :param name: If specified, the logical name that should map to `path`
        :type name: str
        :return: A list of manifest entries to store within the artifact
        :rtype: list(ArtifactManifestEntry)
        """
        pass


class MultiHandler(StorageHandler):

    def __init__(self, handlers=None, default_handler=None):
        self._handlers = {}
        self._default_handler = default_handler

        handlers = handlers or []
        for handler in handlers:
            self._handlers[handler.scheme] = handler

    @property
    def scheme(self):
        raise NotImplementedError()

    def load_path(self, artifact, manifest_entry, local=False):
        url = urlparse(manifest_entry.path)
        if url.scheme not in self._handlers:
            if self._default_handler is not None:
                return self._default_handler.load_path(artifact, manifest_entry, local=local)
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self._handlers[url.scheme].load_path(artifact, manifest_entry, local=local)

    def store_path(self, artifact, path, name=None, reference=False):
        url = urlparse(path)
        if url.scheme not in self._handlers:
            if self._handlers is not None:
                return self._default_handler.store_path(artifact, path, name=name, reference=reference)
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self._handlers[url.scheme].store_path(artifact, path, name=name, reference=reference)


class TrackingHandler(StorageHandler):

    def __init__(self, scheme=None):
        """
        Tracks paths as is, with no modification or special processing. Useful
        when paths being tracked are on file systems mounted at a standardized
        location.

        For example, if the data to track is located on an NFS share mounted on
        /data, then it is sufficient to just track the paths.
        """
        self._scheme = scheme

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        if local:
            # Likely a user error. The tracking handler is
            # oblivious to the underlying paths, so it has
            # no way of actually loading it.
            url = urlparse(manifest_entry.path)
            raise ValueError('Cannot download file at path %s, scheme %s not recognized' %
                             (manifest_entry.path, url.scheme))
        return manifest_entry.path

    def store_path(self, artifact, path, name=None, reference=False):
        url = urlparse(path)
        if not reference:
            raise ValueError('Cannot add file at path %s, scheme %s not recognized' %
                             (path, url.scheme))

        name = name or url.path[1:]  # strip leading slash
        return [ArtifactManifestEntry(name, path, md5=md5_string(path))]


class LocalFileHandler(StorageHandler):

    def __init__(self, scheme=None, upload_callback=None):
        """
        Tracks files or directories on a local filesystem. Directories
        are expanded to create an entry for each file contained within.
        """
        self._scheme = scheme or ""
        self._upload_callback = upload_callback or (lambda entry: None)

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        path = manifest_entry.path
        if not os.path.exists(path):
            raise ValueError('Failed to find file at path %s' % path)

        md5 = md5_file_b64(path)
        if md5 != manifest_entry.md5:
            raise ValueError('Digest mismatch for path %s: expected %s but found %s' %
                             (path, manifest_entry.md5, md5))
        return path

    def store_path(self, artifact, path, name=None, reference=False):
        # We have a single file or directory
        # Note, we follow symlinks for files contained within the directory
        entries = []
        if os.path.isdir(path):
            # We want to map each file to where it will be
            # relative to the root of the artifact. If no
            # name was specified, we assume the for directory
            # 'foo' all files under it will be placed under
            # under '/foo/'. If a name is specified, use that
            # as the root instead. If the name is "/", then
            # simply use that as the root.
            artifact_root = "" if name is "/" else name or os.path.basename(path)
            for dirpath, _, filenames in os.walk(path, followlinks=True):
                for fname in filenames:
                    physical_path = os.path.join(dirpath, fname)
                    logical_path = os.path.join(artifact_root, os.path.relpath(physical_path, start=path))
                    entry = ArtifactManifestEntry(logical_path, physical_path, md5= md5_file_b64(physical_path))
                    if not reference:
                        self._upload_callback(entry)
                    entries.append(entry)
        elif os.path.isfile(path):
            name = name or os.path.basename(path)
            entry = ArtifactManifestEntry(name, path, md5=md5_file_b64(path))
            if not reference:
                self._upload_callback(entry)
            entries.append(entry)
        else:
            raise ValueError('Path "%s" must be a valid file or directory path' % path)
        return entries


class WandbFileHandler(StorageHandler):

    def __init__(self, wandb_upload_callback, scheme=None):
        self._wandb_upload_callback = wandb_upload_callback
        self._scheme = scheme or "wandb"

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        if local:
            # This implementation naively downloads the whole artifact.
            # We can make this smarter by just downloading the requested
            # file.
            url = urlparse(manifest_entry.path)
            return artifact.download(download_l1=False) + url.path

        files = artifact.files(names=[manifest_entry.name])
        if len(files) == 0:
            raise ValueError('Failed to find %s in %s' % (manifest_entry.name, self._artifact.id))
        return artifact.files(names=[manifest_entry.name])[0].url

    def store_path(self, artifact, path, name=None, reference=False):
        # Shouldn't be called. Only local files should be saved.
        raise NotImplementedError()

    def upload_callback(self, manifest_entry):
        self._wandb_upload_callback(manifest_entry.name, manifest_entry.path)
        # Prepend the manifest path entry with the 'wandb:/' scheme.
        # We don't care about storing the physical path in the manifest
        # entry as files within a wandb artifact are mapped to their name.
        manifest_entry.path = '%s:/%s' % (self.scheme, manifest_entry.name)


class S3Handler(StorageHandler):

    def __init__(self, bucket, scheme=None):
        boto3 = util.get_module('boto3', required=True)
        self._s3 = boto3.resource('s3')
        self._bucket = bucket
        self._scheme = scheme or "s3"

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        url = urlparse(manifest_entry.path)
        bucket = url.netloc
        key = url.path[1:]
        version = manifest_entry.extra['versionID']

        extra_args = {}
        if version is None:
            # Object versioning is disabled on the bucket, so just get
            # the latest version and make sure the MD5 matches.
            obj = self._s3.Object(bucket, key)
            md5 = self._md5_from_obj(obj)
            if md5 != manifest_entry.md5:
                raise ValueError('Digest mismatch for object %s/%s: expected %s but found %s',
                                 (self._bucket, key, manifest_entry.md5, md5))
        else:
            obj = self._s3.ObjectVersion(bucket, key, version).Object()
            extra_args['VersionId'] = version

        if not local:
            return manifest_entry.path

        path = '%s/%s' % (artifact.artifact_dir, manifest_entry.name)

        # md5 the path, and skip the download if we already have this file.
        # TODO:
        #   - this will cause etag files to always redownload (maybe ok?).
        #   - this only works for s3 files currently
        if os.path.isfile(path):
            md5 = md5_file_b64(path)
            if md5 == manifest_entry.md5:
                # Skip download.
                return path

        os.makedirs(os.path.dirname(path), exist_ok=True)
        obj.download_file(path, ExtraArgs=extra_args)
        return path

    def store_path(self, artifact, path, name=None, reference=False):
        if not reference:
            # If we wanted to be fancy, we could copy the file. But that could use a
            # ton of bandwidth and is almost certainly not what the user wants.
            raise ValueError('Cannot add an s3 path as a file. Use a reference instead.')

        url = urlparse(path)
        bucket = url.netloc
        key = url.path[1:]  # strip leading slash
        obj = self._s3.Object(bucket, key)

        md5 = self._md5_from_obj(obj)
        extra = self._extra_from_obj(obj)

        return [ArtifactManifestEntry(name or key, path, md5, extra)]

    def upload_callback(self, manifest_entry):
        key = self._content_addressed_path(manifest_entry.md5)
        obj = self._s3.Object(self._bucket, key)

        # Only upload the file if it doesn't already exist.
        if len(list(self._s3.Bucket(self._bucket).objects.filter(Prefix=key))) == 0:
            obj.upload_file(manifest_entry.path, ExtraArgs={
                'Metadata': {
                    'md5': manifest_entry.md5,
                }
            })

        manifest_entry.path = 's3://%s/%s' % (self._bucket, key)
        manifest_entry.extra = self._extra_from_obj(obj)

    @staticmethod
    def _md5_from_obj(obj):
        # If we're lucky, the MD5 is directly in the metadata.
        if 'md5' in obj.metadata:
            return obj.metadata['md5']
        # Unfortunately, this is not the true MD5 of the file. Without
        # streaming the file and computing an MD5 manually, there is no
        # way to obtain the true MD5.
        return obj.e_tag[1:-1]  # escape leading and trailing quote

    @staticmethod
    def _extra_from_obj(obj):
        return {
            'etag': obj.e_tag[1:-1],  # escape leading and trailing quote
            'versionID': obj.version_id,
        }

    @staticmethod
    def _content_addressed_path(md5):
        # TODO: is this the structure we want? not at all human
        # readable, but that's probably OK. don't want people
        # poking around in the bucket
        return 'wandb/%s' % base64.b64encode(md5.encode("ascii")).decode("ascii")
