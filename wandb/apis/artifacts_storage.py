import base64
import hashlib
import os
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

    def load_path(self, path):
        print(self.entries)
        if path not in self.entries:
            raise ValueError('Failed to find "%s" in artifact manifest' % path)
        return self.storage_policy.load_path(self.entries[path])

    def store_paths(self, paths):
        if isinstance(paths, list):
            for path in paths:
                for entry in self.storage_policy.store_path(path):
                    self.entries[entry.name] = entry
        if isinstance(paths, dict):
            for name, path in paths.items():
                for entry in self.storage_policy.store_path(path, name=name):
                    self.entries[entry.name] = entry
        else:
            path = paths
            for entry in self.storage_policy.store_path(path):
                self.entries[entry.name] = entry
        return self.storage_policy.file_specs


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

    def __init__(self, artifact, storage_handlers=None):
        storage_handlers = storage_handlers or []
        self.artifact = artifact
        self.storage_handlers = {}
        self.file_specs = {}
        for handler in storage_handlers:
            self.storage_handlers[handler.scheme] = handler

    @abstractmethod
    def config(self):
        pass

    def load_path(self, manifest_entry):
        url = urlparse(manifest_entry.path)
        if url.scheme not in self.storage_handlers:
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self.storage_handlers[url.scheme].load_path(self.artifact, manifest_entry)

    def store_path(self, path, name=None):
        url = urlparse(path)
        if url.scheme not in self.storage_handlers:
            raise ValueError('No storage handler registered for scheme "%s"' % url.scheme)
        return self.storage_handlers[url.scheme].store_path(self.artifact, path, name=name)


class WandbStoragePolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-storage-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        # No extra configuration needed.
        return cls(artifact)

    def __init__(self, artifact):
        super(WandbStoragePolicy, self).__init__(artifact, storage_handlers=[
            FileUploadHandler(
                scheme="",
                upload_callback=self._upload_callback
            ),
            WandbDownloadHandler(
                scheme="wandb"
            )
        ])

    def config(self):
        return None

    def _upload_callback(self, name, path):
        self.file_specs[name] = path
        return 'wandb:/' + path


class S3UploadPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-s3-upload-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        if 'bucket' not in config:
            raise ValueError('Bucket name not found in config')
        return cls(artifact, bucket_name=config['bucket'])

    def __init__(self, artifact, bucket_name):
        self.bucket_name = bucket_name
        # TODO: implement handlers
        super(S3UploadPolicy, self).__init__(artifact)

    def config(self):
        return {
            'bucket': self.bucket_name
        }

    def _upload_callback(self):
        # TODO: implement me
        pass


class TrackingPolicy(StoragePolicy):

    @classmethod
    def name(cls):
        return 'wandb-tracking-policy-v1'

    @classmethod
    def from_config(cls, artifact, config):
        return cls(artifact)

    def __init__(self, artifact):
        super(TrackingPolicy, self).__init__(artifact)

    def config(self):
        return None

    def load_path(self, manifest_entry):
        return TrackingHandler().load_path(self.artifact, manifest_entry)

    def store_path(self, path, name=None):
        return TrackingHandler().store_path(self.artifact, path, name=name)


class StorageHandler(ABC):

    def __init__(self, scheme=None):
        self._scheme = scheme
        super(StorageHandler, self).__init__()

    @property
    def scheme(self):
        """
        :return: The scheme to which this handler applies.
        :rtype: str
        """
        return self._scheme

    @abstractmethod
    def load_path(self, artifact, manifest_entry):
        """
        Loads the file or directory within the specified artifact given its
        corresponding index entry.

        :param artifact: The artifact to load
        :type artifact: Artifact
        :param manifest_entry: The index entry to load
        :type manifest_entry: ArtifactManifestEntry
        :return: A path to the file represented by `index_entry`
        :rtype: os.PathLike
        """
        pass

    @abstractmethod
    def store_path(self, artifact, path, name=None):
        """
        Stores the file or directory at the given path within the specified artifact.

        :param artifact: The artifact to store
        :type artifact: Artifact
        :param path: The path to store
        :type path: str
        :param name: If specified, the logical name that should map to `path`
        :type name: str
        :return: A list of manifest entries to store within the artifact
        :rtype: list(ArtifactManifestEntry)
        """
        pass


class TrackingHandler(StorageHandler):

    def __init__(self, scheme=None):
        super(TrackingHandler, self).__init__(scheme)

    def load_path(self, artifact, manifest_entry):
        return manifest_entry.path

    def store_path(self, artifact, path, name=None):
        url = urlparse(path)
        name = name or os.path.basename(url.path)
        return [ArtifactManifestEntry(name, path, md5=md5_string(path))]


class FileUploadHandler(StorageHandler):

    def __init__(self, scheme=None, upload_callback=None):
        self.upload_callback = upload_callback or (lambda name, path: path)
        super(FileUploadHandler, self).__init__(scheme)

    def load_path(self, artifact, manifest_entry):
        raise NotImplementedError()

    def store_path(self, artifact, path, name=None):
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
                    upload_path = self.upload_callback(logical_path, physical_path)
                    entries.append(
                        ArtifactManifestEntry(logical_path, upload_path, md5=md5_file_b64(physical_path)))
        elif os.path.isfile(path):
            name = name or os.path.basename(path)

            # The full path is not required in the manifest entry since the
            # file will be uploaded at the root of the artifact.
            upload_path = self.upload_callback(name, path)
            entries.append(
                ArtifactManifestEntry(name, upload_path, md5=md5_file_b64(path)))
        return entries


class WandbDownloadHandler(StorageHandler):

    def __init__(self, scheme=None):
        super(WandbDownloadHandler, self).__init__(scheme)

    def load_path(self, artifact, manifest_entry):
        # For now just download the whole artifact. We can make this smarter
        # later by using file patterns.
        path = manifest_entry.path[len('wandb:/'):]
        return artifact.download() + '/' + path

    def store_path(self, artifact, path, name=None):
        raise NotImplementedError()
