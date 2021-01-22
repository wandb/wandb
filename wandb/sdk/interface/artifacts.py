#
import base64
import binascii
import codecs
import hashlib
import os

from wandb import env
from wandb import util


def md5_string(string):
    hash_md5 = hashlib.md5()
    hash_md5.update(string.encode())
    return base64.b64encode(hash_md5.digest()).decode("ascii")


def b64_string_to_hex(string):
    return binascii.hexlify(base64.standard_b64decode(string)).decode("ascii")


def md5_hash_file(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            hash_md5.update(chunk)
    return hash_md5


def md5_file_b64(path):
    return base64.b64encode(md5_hash_file(path).digest()).decode("ascii")


def md5_file_hex(path):
    return md5_hash_file(path).hexdigest()


def bytes_to_hex(bytestr):
    # Works in python2 / python3
    return codecs.getencoder("hex")(bytestr)[0]


class ArtifactManifest(object):
    @classmethod
    # TODO: we don't need artifact here.
    def from_manifest_json(cls, artifact, manifest_json):
        if "version" not in manifest_json:
            raise ValueError("Invalid manifest format. Must contain version field.")
        version = manifest_json["version"]
        for sub in cls.__subclasses__():
            if sub.version() == version:
                return sub.from_manifest_json(artifact, manifest_json)

    @classmethod
    def version(cls):
        pass

    def __init__(self, artifact, storage_policy, entries=None):
        self.artifact = artifact
        self.storage_policy = storage_policy
        self.entries = entries or {}

    def to_manifest_json(self):
        raise NotImplementedError()

    def digest(self):
        raise NotImplementedError()

    def add_entry(self, entry):
        if (
            entry.path in self.entries
            and entry.digest != self.entries[entry.path].digest
        ):
            raise ValueError("Cannot add the same path twice: %s" % entry.path)
        self.entries[entry.path] = entry

    def get_entry_by_path(self, path):
        return self.entries.get(path)


class StorageLayout(object):
    V1 = "V1"
    V2 = "V2"


class StoragePolicy(object):
    @classmethod
    def lookup_by_name(cls, name):
        for sub in cls.__subclasses__():
            if sub.name() == name:
                return sub
        return None

    @classmethod
    def name(cls):
        pass

    @classmethod
    def from_config(cls, config):
        pass

    def config(self):
        pass

    def load_file(self, artifact, name, manifest_entry):
        raise NotImplementedError

    def store_file(self, artifact_id, entry, preparer, progress_callback=None):
        raise NotImplementedError

    def store_reference(
        self, artifact, path, name=None, checksum=True, max_objects=None
    ):
        raise NotImplementedError

    def load_reference(self, artifact, name, manifest_entry, local=False):
        raise NotImplementedError


class StorageHandler(object):
    def scheme(self):
        """
        :return: The scheme to which this handler applies.
        :rtype: str
        """
        pass

    def load_path(self, artifact, manifest_entry, local=False):
        """
        Loads the file or directory within the specified artifact given its
        corresponding index entry.

        :param manifest_entry: The index entry to load
        :type manifest_entry: ArtifactManifestEntry
        :return: A path to the file represented by `index_entry`
        :rtype: os.PathLike
        """
        pass

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
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


class ArtifactsCache(object):
    def __init__(self, cache_dir):
        self._cache_dir = cache_dir
        util.mkdir_exists_ok(self._cache_dir)
        self._md5_obj_dir = os.path.join(self._cache_dir, "obj", "md5")
        self._etag_obj_dir = os.path.join(self._cache_dir, "obj", "etag")
        self._artifacts_by_id = {}

    def check_md5_obj_path(self, b64_md5, size):
        hex_md5 = util.bytes_to_hex(base64.b64decode(b64_md5))
        path = os.path.join(self._cache_dir, "obj", "md5", hex_md5[:2], hex_md5[2:])
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False

    def check_etag_obj_path(self, etag, size):
        path = os.path.join(self._cache_dir, "obj", "etag", etag[:2], etag[2:])
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path, True
        util.mkdir_exists_ok(os.path.dirname(path))
        return path, False

    def get_artifact(self, artifact_id):
        return self._artifacts_by_id.get(artifact_id)

    def store_artifact(self, artifact):
        self._artifacts_by_id[artifact.id] = artifact


_artifacts_cache = None


def get_artifacts_cache():
    global _artifacts_cache
    if _artifacts_cache is None:
        cache_dir = os.path.join(env.get_cache_dir(), "artifacts")
        _artifacts_cache = ArtifactsCache(cache_dir)
    return _artifacts_cache
