import base64
import hashlib
import os
import sys
from abc import ABC, abstractmethod
from six.moves.urllib.parse import urlparse


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

    def load_path(self, path, local=False):
        print(self.entries)
        if path not in self.entries:
            raise ValueError('Failed to find "%s" in artifact manifest' % path)
        return self.storage_policy.load_path(self.entries[path], local=local)

    def store_paths(self, paths, reference=False):
        if isinstance(paths, list):
            for path in paths:
                for entry in self.storage_policy.store_path(path, reference=reference):
                    self.entries[entry.name] = entry
        if isinstance(paths, dict):
            for name, path in paths.items():
                for entry in self.storage_policy.store_path(path, name=name, reference=reference):
                    self.entries[entry.name] = entry
        else:
            path = paths
            for entry in self.storage_policy.store_path(path, reference=reference):
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

        return cls(artifact, storage_policy_cls.from_config(artifact, storage_policy_config), entries)

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
    def from_config(cls, artifact, config):
        pass

    @abstractmethod
    def config(self):
        pass

    @abstractmethod
    def load_path(self, manifest_entry, local=False):
        pass

    @abstractmethod
    def store_path(self, path, name=None, reference=False):
        pass


class WandbStoragePolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-storage-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        def upload_callback(name, path):
            # Not valid to upload from here.
            raise NotImplementedError()

        return cls(artifact, upload_callback)

    def __init__(self, artifact, wandb_upload_callback):
        wandb = WandbFileHandler(artifact, wandb_upload_callback)
        local = LocalFileHandler(upload_callback=wandb.upload_callback)

        self._artifact = artifact
        self._handler = MultiHandler(handlers=[
            wandb,
            local,
        ], default_handler=TrackingHandler())

    def config(self):
        return None

    def load_path(self, manifest_entry, local=False):
        return self._handler.load_path(manifest_entry, local=local)

    def store_path(self, path, name=None, reference=False):
        return self._handler.store_path(path, name=name, reference=reference)


class S3BucketPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-s3-bucket-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        if 'bucket' not in config:
            raise ValueError('Bucket name not found in config')
        return cls(artifact, config['bucket'])

    def __init__(self, artifact, bucket):
        self._bucket = bucket
        s3 = S3Handler(artifact, bucket)
        local = LocalFileHandler(upload_callback=s3.upload_callback)

        self._handler = MultiHandler(handlers=[
            s3,
            local,
        ], default_handler=TrackingHandler())

    def config(self):
        return {
            'bucket': self._bucket
        }

    def load_path(self, manifest_entry, local=False):
        return self._handler.load_path(manifest_entry, local=local)

    def store_path(self, path, name=None, reference=False):
        return self._handler.store_path(path, name=name, reference=reference)


class TrackingPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-tracking-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        return cls(artifact)

    def __init__(self, artifact):
        self._artifact = artifact
        self._handler = MultiHandler(default_handler=TrackingHandler())

    def config(self):
        return None

    def load_path(self, manifest_entry, local=False):
        return self._handler.load_path(manifest_entry, local=local)

    def store_path(self, path, name=None, reference=False):
        return self._handler.store_path(path, name=name, reference=reference)


class StorageHandler(ABC):

    @abstractmethod
    def scheme(self):
        """
        :return: The scheme to which this handler applies.
        :rtype: str
        """
        pass

    @abstractmethod
    def load_path(self, manifest_entry, remote=False):
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
    def store_path(self, path, name=None, reference=False):
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

    def load_path(self, manifest_entry, local=False):
        url = urlparse(manifest_entry.path)
        if url.scheme not in self._handlers:
            if self._default_handler is not None:
                return self._default_handler.load_path(manifest_entry, local=local)
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self._handlers[url.scheme].load_path(manifest_entry, local=local)

    def store_path(self, path, name=None, reference=False):
        url = urlparse(path)
        if url.scheme not in self._handlers:
            if self._handlers is not None:
                return self._default_handler.store_path(path, name=name, reference=reference)
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self._handlers[url.scheme].store_path(path, name=name, reference=reference)


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

    def load_path(self, manifest_entry, local=False):
        if local:
            # Likely a user error. The tracking handler is
            # oblivious to the underlying paths, so it has
            # no way of actually loading it.
            url = urlparse(manifest_entry.path)
            raise ValueError('Cannot download file at path %s, scheme %s not recognized' %
                             (manifest_entry.path, url.scheme))
        return manifest_entry.path

    def store_path(self, path, name=None, reference=False):
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

    def load_path(self, manifest_entry, local=False):
        path = manifest_entry.path
        if not os.path.exists(path):
            raise ValueError('Failed to find file at path %s' % path)

        md5 = md5_file_b64(path)
        if md5 != manifest_entry.md5:
            raise ValueError('Digest mismatch for path %s: expected %s but found %s' %
                             (path, manifest_entry.md5, md5))
        return path

    def store_path(self, path, name=None, reference=False):
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
        return entries


class WandbFileHandler(StorageHandler):

    def __init__(self, artifact, wandb_upload_callback, scheme=None):
        self._artifact = artifact
        self._wandb_upload_callback = wandb_upload_callback
        self._scheme = scheme or "wandb"

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, manifest_entry, local=False):
        if local:
            # This implementation naively downloads the whole artifact.
            # We can make this smarter by just downloading the requested
            # file.
            url = urlparse(manifest_entry.path)
            return self._artifact.download() + url.path

        files = self._artifact.files(names=[manifest_entry.name])
        if len(files) == 0:
            raise ValueError('Failed to find %s in %s' % (manifest_entry.name, self._artifact.id))
        return self._artifact.files(names=[manifest_entry.name])[0].url

    def store_path(self, path, name=None, reference=False):
        # Shouldn't be called. Only local files should be saved.
        raise NotImplementedError()

    def upload_callback(self, manifest_entry):
        self._wandb_upload_callback(manifest_entry.name, manifest_entry.path)
        # Prepend the manifest path entry with the 'wandb:/' scheme.
        # We don't care about storing the physical path in the manifest
        # entry as files within a wandb artifact are mapped to their name.
        manifest_entry.path = '%s:/%s' % (self.scheme, manifest_entry.name)


class S3Handler(StorageHandler):

    def __init__(self, artifact, bucket, scheme=None):
        if 'boto3' not in sys.modules:
            import boto3
        self._s3 = boto3.client('s3')
        self._bucket = bucket
        self._artifact = artifact
        self._scheme = scheme or "s3"

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, manifest_entry, local=False):
        url = urlparse(manifest_entry.path)
        bucket = url.netloc
        key = url.path[1:]
        version = manifest_entry.extra['versionID']
        obj = self._s3.ObjectVersion(bucket, key, version).Object()
        md5 = self._md5_from_obj(obj)
        if md5 != manifest_entry.md5:
            raise ValueError('Digest mismatch for object %s/%s: expected %s but found %s',
                             (self._bucket, key, manifest_entry.md5, md5))
        if not local:
            return manifest_entry.path

        path = '%s/%s' % (self._artifact.artifact_dir, manifest_entry.name)
        obj.download_file(path)
        return path

    def store_path(self, path, name=None, reference=False):
        if not reference:
            # If we wanted to be fancy, we could copy the file. But that could use a
            # ton of bandwidth and is almost certainly not what the user wants.
            raise ValueError('Cannot add an s3 path as a file. Use a reference instead.')

        # Capture metadata from the s3 bucket.
        url = urlparse(path)
        bucket = url.netloc
        key = url.path[1:]  # strip leading slash
        obj = self._s3.Object(bucket, key)

        md5 = obj.e_tag
        extra = self._extra_from_obj(obj)

        return [ArtifactManifestEntry(key, path, md5, extra)]

    def upload_callback(self, manifest_entry):
        key = self._content_addressed_path(manifest_entry.md5)
        obj = self._s3.Object(self._bucket, key)

        manifest_entry.path = 's3://%s/%s' % (self._bucket, key)
        obj.upload_file(manifest_entry.path, ExtraArgs={
            'Metadata': {
                'md5': manifest_entry.md5,
            }
        })

        # Capture ETags and VersionIDs
        manifest_entry.extra = self._extra_from_obj(obj)

    @staticmethod
    def _md5_from_obj(obj):
        # If we're lucky, the MD5 is directly in the metadata.
        if 'md5' in obj.metadata:
            return obj.metadata['md5']
        # Unfortunately, this is not the true MD5 of the file. Without
        # streaming the file and computing an MD5 manually, there is no
        # way to obtain the true MD5.
        return obj.e_tag

    @staticmethod
    def _extra_from_obj(obj):
        return {
            'etag': obj.e_tag,
            'versionID': obj.version_id,
        }

    @staticmethod
    def _content_addressed_path(md5):
        # TODO: is this the structure we want? not at all human
        # readable, but that's probably OK. don't want people
        # poking around in the bucket
        return 'wandb/%s' % md5
