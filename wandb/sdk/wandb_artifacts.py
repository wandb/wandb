#
import base64
import contextlib
import hashlib
import os
import re
import shutil
import time

import requests
from six.moves.urllib.parse import quote, urlparse
import wandb
from wandb import env
from wandb import util
from wandb.apis import InternalApi, PublicApi
from wandb.apis.public import Artifact as PublicArtifact
from wandb.compat import tempfile as compat_tempfile
from wandb.data_types import WBValue
from wandb.errors.error import CommError
from wandb.errors.term import termlog, termwarn

from .interface.artifacts import (  # noqa: F401 pylint: disable=unused-import
    Artifact as ArtifactInterface,
    ArtifactEntry,
    ArtifactManifest,
    ArtifactsCache,
    b64_string_to_hex,
    get_artifacts_cache,
    md5_file_b64,
    StorageHandler,
    StorageLayout,
    StoragePolicy,
)

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import List, Optional, Union

# This makes the first sleep 1s, and then doubles it up to total times,
# which makes for ~18 hours.
_REQUEST_RETRY_STRATEGY = requests.packages.urllib3.util.retry.Retry(
    backoff_factor=1,
    total=16,
    status_forcelist=(308, 408, 409, 429, 500, 502, 503, 504),
)

_REQUEST_POOL_CONNECTIONS = 64

_REQUEST_POOL_MAXSIZE = 64


class Artifact(ArtifactInterface):
    """
    Constructs an empty artifact whose contents can be populated using its
    `add` family of functions. Once the artifact has all the desired files,
    you can call `wandb.log_artifact()` to log it.


    Arguments:
        name: (str) A human-readable name for this artifact, which is how you
            can identify this artifact in the UI or reference it in `use_artifact`
            calls. Names can contain letters, numbers, underscores, hyphens, and
            dots. The name must be unique across a project.
        type: (str) The type of the artifact, which is used to organize and differentiate
            artifacts. Common types include `dataset` or `model`, but you can use any string
            containing letters, numbers, underscores, hyphens, and dots.
        description: (str, optional) Free text that offers a description of the artifact. The
            description is markdown rendered in the UI, so this is a good place to place tables,
            links, etc.
        metadata: (dict, optional) Structured data associated with the artifact,
            for example class distribution of a dataset. This will eventually be queryable
            and plottable in the UI. There is a hard limit of 100 total keys.

    Examples:
        Basic usage
        ```
        wandb.init()

        artifact = wandb.Artifact('mnist', type='dataset')
        artifact.add_dir('mnist/')
        wandb.log_artifact(artifact)
        ```

    Raises:
        Exception: if problem.

    Returns:
        An `Artifact` object.
    """

    _added_objs: dict
    _added_local_paths: dict
    _distributed_id: Optional[str]
    _metadata: dict
    _logged_artifact: Optional[ArtifactInterface]

    def __init__(
        self,
        name: str,
        type: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if not re.match(r"^[a-zA-Z0-9_\-.]+$", name):
            raise ValueError(
                "Artifact name may only contain alphanumeric characters, dashes, underscores, and dots. "
                'Invalid name: "%s"' % name
            )
        # TODO: this shouldn't be a property of the artifact. It's a more like an
        # argument to log_artifact.
        storage_layout = StorageLayout.V2
        if env.get_use_v1_artifacts():
            storage_layout = StorageLayout.V1

        self._storage_policy = WandbStoragePolicy(
            config={
                "storageLayout": storage_layout,
                #  TODO: storage region
            }
        )
        self._api = InternalApi()
        self._final = False
        self._digest = ""
        self._file_entries = None
        self._manifest = ArtifactManifestV1(self, self._storage_policy)
        self._cache = get_artifacts_cache()
        self._added_objs = {}
        self._added_local_paths = {}
        # You can write into this directory when creating artifact files
        self._artifact_dir = compat_tempfile.TemporaryDirectory(
            missing_ok_on_cleanup=True
        )
        self._type = type
        self._name = name
        self._description = description
        self._metadata = metadata or {}
        self._distributed_id = None
        self._logged_artifact = None

    @property
    def id(self) -> Optional[str]:
        if self._logged_artifact:
            return self._logged_artifact.id

        # The artifact hasn't been saved so an ID doesn't exist yet.
        return None

    @property
    def version(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.version

        raise ValueError(
            "Cannot call version on an artifact before it has been logged or in offline mode"
        )

    @property
    def entity(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.entity

        return self._api.settings("entity") or self._api.viewer().get("entity")

    @property
    def project(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.project

        return self._api.settings("project")

    @property
    def manifest(self) -> ArtifactManifest:
        if self._logged_artifact:
            return self._logged_artifact.manifest

        self.finalize()
        return self._manifest

    @property
    def digest(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.digest

        self.finalize()
        # Digest will be none if the artifact hasn't been saved yet.
        return self._digest

    @property
    def type(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.type

        return self._type

    @property
    def name(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.name

        return self._name

    @property
    def state(self) -> str:
        if self._logged_artifact:
            return self._logged_artifact.state

        return "PENDING"

    @property
    def size(self) -> int:
        if self._logged_artifact:
            return self._logged_artifact.size

        return sum([entry.size for entry in self._manifest.entries])

    @property
    def description(self) -> Optional[str]:
        if self._logged_artifact:
            return self._logged_artifact.description

        return self._description

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        if self._logged_artifact:
            self._logged_artifact.description = desc
            return

        self._description = desc

    @property
    def metadata(self) -> dict:
        if self._logged_artifact:
            return self._logged_artifact.metadata

        return self._metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        if self._logged_artifact:
            self._metadata = metadata
            return

        self._metadata = metadata

    @property
    def aliases(self) -> List[str]:
        if self._logged_artifact:
            return self._logged_artifact.aliases

        raise ValueError(
            "Cannot call aliases on an artifact before it has been logged or in offline mode"
        )

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        """
        Arguments:
            aliases: (list) The list of aliases associated with this artifact.
        """
        if self._logged_artifact:
            self._logged_artifact.aliases = aliases
            return

        raise ValueError(
            "Cannot set aliases on an artifact before it has been logged or in offline mode"
        )

    @property
    def distributed_id(self) -> Optional[str]:
        return self._distributed_id

    @distributed_id.setter
    def distributed_id(self, distributed_id: Optional[str]) -> None:
        self._distributed_id = distributed_id

    def used_by(self) -> List["wandb.apis.public.Run"]:
        if self._logged_artifact:
            return self._logged_artifact.used_by()

        raise ValueError(
            "Cannot call used_by on an artifact before it has been logged or in offline mode"
        )

    def logged_by(self) -> "wandb.apis.public.Run":
        if self._logged_artifact:
            return self._logged_artifact.logged_by()

        raise ValueError(
            "Cannot call logged_by on an artifact before it has been logged or in offline mode"
        )

    @contextlib.contextmanager
    def new_file(self, name: str, mode: str = "w"):
        self._ensure_can_add()
        path = os.path.join(self._artifact_dir.name, name.lstrip("/"))
        if os.path.exists(path):
            raise ValueError(
                'File with name "%s" already exists at "%s"' % (name, path)
            )

        util.mkdir_exists_ok(os.path.dirname(path))
        with util.fsync_open(path, mode) as f:
            yield f

        self.add_file(path, name=name)

    def add_file(
        self,
        local_path: str,
        name: Optional[str] = None,
        is_tmp: Optional[bool] = False,
    ):
        self._ensure_can_add()
        if not os.path.isfile(local_path):
            raise ValueError("Path is not a file: %s" % local_path)

        name = name or os.path.basename(local_path)
        digest = md5_file_b64(local_path)

        if is_tmp:
            file_path, file_name = os.path.split(name)
            file_name_parts = file_name.split(".")
            file_name_parts[0] = b64_string_to_hex(digest)[:8]
            name = os.path.join(file_path, ".".join(file_name_parts))

        return self._add_local_file(name, local_path, digest=digest)

    def add_dir(self, local_path: str, name: Optional[str] = None) -> None:
        self._ensure_can_add()
        if not os.path.isdir(local_path):
            raise ValueError("Path is not a directory: %s" % local_path)

        termlog(
            "Adding directory to artifact (%s)... "
            % os.path.join(".", os.path.normpath(local_path)),
            newline=False,
        )
        start_time = time.time()

        paths = []
        for dirpath, _, filenames in os.walk(local_path, followlinks=True):
            for fname in filenames:
                physical_path = os.path.join(dirpath, fname)
                logical_path = os.path.relpath(physical_path, start=local_path)
                if name is not None:
                    logical_path = os.path.join(name, logical_path)
                paths.append((logical_path, physical_path))

        def add_manifest_file(log_phy_path):
            logical_path, physical_path = log_phy_path
            self._add_local_file(logical_path, physical_path)

        import multiprocessing.dummy  # this uses threads

        num_threads = 8
        pool = multiprocessing.dummy.Pool(num_threads)
        pool.map(add_manifest_file, paths)
        pool.close()
        pool.join()

        termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)

    def add_reference(
        self,
        uri: Union[ArtifactEntry, str],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ):
        self._ensure_can_add()

        # This is a bit of a hack, we want to check if the uri is a of the type
        # ArtifactEntry which is a private class returned by Artifact.get_path in
        # wandb/apis/public.py. If so, then recover the reference URL.
        if isinstance(uri, ArtifactEntry) and uri.parent_artifact() != self:
            ref_url_fn = uri.ref_url
            uri = ref_url_fn()
        url = urlparse(str(uri))
        if not url.scheme:
            raise ValueError(
                "References must be URIs. To reference a local file, use file://"
            )

        manifest_entries = self._storage_policy.store_reference(
            self, uri, name=name, checksum=checksum, max_objects=max_objects
        )
        for entry in manifest_entries:
            self._manifest.add_entry(entry)

        return manifest_entries

    def add(self, obj: WBValue, name: str):
        self._ensure_can_add()

        # Validate that the object is wandb.Media type
        if not isinstance(obj, WBValue):
            raise ValueError("Can only add `obj` which subclass wandb.WBValue")

        obj_id = id(obj)
        if obj_id in self._added_objs:
            return self._added_objs[obj_id]["entry"]

        # If the object is coming from another artifact, save it as a reference
        if obj.artifact_source and obj.artifact_source.name:
            ref_path = obj.artifact_source.artifact.get_path(
                type(obj).with_suffix(obj.artifact_source.name)
            )
            return self.add_reference(ref_path, type(obj).with_suffix(name))[0]

        val = obj.to_json(self)
        name = obj.with_suffix(name)
        entry = self._manifest.get_entry_by_path(name)
        if entry is not None:
            return entry
        with self.new_file(name) as f:
            import json

            # TODO: Do we need to open with utf-8 codec?
            f.write(json.dumps(val, sort_keys=True))

        # Note, we add the file from our temp directory.
        # It will be added again later on finalize, but succeed since
        # the checksum should match
        entry = self.add_file(os.path.join(self._artifact_dir.name, name), name)
        self._added_objs[obj_id] = {"entry": entry, "obj": obj}

        return entry

    def get_path(self, name: str):
        if self._logged_artifact:
            return self._logged_artifact.get_path(name)

        raise ValueError(
            "Cannot load paths from an artifact before it has been logged or in offline mode"
        )

    def get(self, name: str):
        if self._logged_artifact:
            return self._logged_artifact.get(name)

        raise ValueError(
            "Cannot call get on an artifact before it has been logged or in offline mode"
        )

    def download(self, root: str = None, recursive: bool = False):
        if self._logged_artifact:
            return self._logged_artifact.download(root=root, recursive=recursive)

        raise ValueError(
            "Cannot call download on an artifact before it has been logged or in offline mode"
        )

    def checkout(self, root: Optional[str] = None) -> str:
        if self._logged_artifact:
            return self._logged_artifact.checkout(root=root)

        raise ValueError(
            "Cannot call checkout on an artifact before it has been logged or in offline mode"
        )

    def verify(self, root: Optional[str] = None):
        if self._logged_artifact:
            return self._logged_artifact.verify(root=root)

        raise ValueError(
            "Cannot call verify on an artifact before it has been logged or in offline mode"
        )

    def save(self) -> None:
        if self._logged_artifact:
            return self._logged_artifact.save()

        raise ValueError(
            "Cannot call save on an artifact before it has been logged or in offline mode"
        )

    def delete(self) -> None:
        if self._logged_artifact:
            return self._logged_artifact.delete()

        raise ValueError(
            "Cannot call delete on an artifact before it has been logged or in offline mode"
        )

    def wait(self) -> ArtifactInterface:
        if self._logged_artifact:
            return self._logged_artifact.wait()

        raise ValueError(
            "Cannot call wait on an artifact before it has been logged or in offline mode"
        )

    def get_added_local_path_name(self, local_path: str):
        """
        Get the artifact relative name of a file added by a local filesystem path.

        Arguments:
            local_path: (str) The local path to resolve into an artifact relative name.

        Returns:
            str: The artifact relative name.

        Examples:
            Basic usage
            ```
            artifact = wandb.Artifact('my_dataset', type='dataset')
            artifact.add_file('path/to/file.txt', name='artifact/path/file.txt')

            # Returns `artifact/path/file.txt`:
            name = artifact.get_added_local_path_name('path/to/file.txt')
            ```
        """
        entry = self._added_local_paths.get(local_path, None)
        if entry is None:
            return None
        return entry.path

    def finalize(self):
        """
        Marks this artifact as final, which disallows further additions to the artifact.
        This happens automatically when calling `log_artifact`.


        Returns:
            None
        """
        if self._final:
            return self._file_entries

        # mark final after all files are added
        self._final = True
        self._digest = self._manifest.digest()

    def _ensure_can_add(self):
        if self._final:
            raise ValueError("Can't add to finalized artifact.")

    def _add_local_file(self, name, path, digest=None):
        digest = digest or md5_file_b64(path)
        size = os.path.getsize(path)

        cache_path, hit = self._cache.check_md5_obj_path(digest, size)
        if not hit:
            shutil.copyfile(path, cache_path)

        entry = ArtifactManifestEntry(
            name, None, digest=digest, size=size, local_path=cache_path,
        )

        self._manifest.add_entry(entry)
        self._added_local_paths[path] = entry
        return entry


class ArtifactManifestV1(ArtifactManifest):
    @classmethod
    def version(cls):
        return 1

    @classmethod
    def from_manifest_json(cls, artifact, manifest_json):
        if manifest_json["version"] != cls.version():
            raise ValueError(
                "Expected manifest version 1, got %s" % manifest_json["version"]
            )

        storage_policy_name = manifest_json["storagePolicy"]
        storage_policy_config = manifest_json.get("storagePolicyConfig", {})
        storage_policy_cls = StoragePolicy.lookup_by_name(storage_policy_name)
        if storage_policy_cls is None:
            raise ValueError('Failed to find storage policy "%s"' % storage_policy_name)

        entries = {
            name: ArtifactManifestEntry(
                path=name,
                digest=val["digest"],
                birth_artifact_id=val.get("birthArtifactID"),
                ref=val.get("ref"),
                size=val.get("size"),
                extra=val.get("extra"),
                local_path=val.get("local_path"),
            )
            for name, val in manifest_json["contents"].items()
        }

        return cls(
            artifact, storage_policy_cls.from_config(storage_policy_config), entries
        )

    def __init__(self, artifact, storage_policy, entries=None):
        super(ArtifactManifestV1, self).__init__(
            artifact, storage_policy, entries=entries
        )

    def to_manifest_json(self):
        """This is the JSON that's stored in wandb_manifest.json

        If include_local is True we also include the local paths to files. This is
        used to represent an artifact that's waiting to be saved on the current
        system. We don't need to include the local paths in the artifact manifest
        contents.
        """
        contents = {}
        for entry in sorted(self.entries.values(), key=lambda k: k.path):
            json_entry = {
                "digest": entry.digest,
            }
            if entry.birth_artifact_id:
                json_entry["birthArtifactID"] = entry.birth_artifact_id
            if entry.ref:
                json_entry["ref"] = entry.ref
            if entry.extra:
                json_entry["extra"] = entry.extra
            if entry.size is not None:
                json_entry["size"] = entry.size
            contents[entry.path] = json_entry
        return {
            "version": self.__class__.version(),
            "storagePolicy": self.storage_policy.name(),
            "storagePolicyConfig": self.storage_policy.config() or {},
            "contents": contents,
        }

    def digest(self):
        hasher = hashlib.md5()
        hasher.update("wandb-artifact-manifest-v1\n".encode())
        for (name, entry) in sorted(self.entries.items(), key=lambda kv: kv[0]):
            hasher.update("{}:{}\n".format(name, entry.digest).encode())
        return hasher.hexdigest()


class ArtifactManifestEntry(object):
    def __init__(
        self,
        path,
        ref,
        digest,
        birth_artifact_id=None,
        size=None,
        extra=None,
        local_path=None,
    ):
        if local_path is not None and size is None:
            raise AssertionError(
                "programming error, size required when local_path specified"
            )
        self.path = util.to_forward_slash_path(path)
        self.ref = ref  # This is None for files stored in the artifact.
        self.digest = digest
        self.birth_artifact_id = birth_artifact_id
        self.size = size
        self.extra = extra or {}
        # This is not stored in the manifest json, it's only used in the process
        # of saving
        self.local_path = local_path

    def __repr__(self):
        if self.ref is not None:
            summary = "ref: %s/%s" % (self.ref, self.path)
        else:
            summary = "digest: %s" % self.digest

        return "<ManifestEntry %s>" % summary


class WandbStoragePolicy(StoragePolicy):
    @classmethod
    def name(cls):
        return "wandb-storage-policy-v1"

    @classmethod
    def from_config(cls, config):
        return cls(config=config)

    def __init__(self, config=None):
        self._cache = get_artifacts_cache()
        self._config = config or {}
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=_REQUEST_RETRY_STRATEGY,
            pool_connections=_REQUEST_POOL_CONNECTIONS,
            pool_maxsize=_REQUEST_POOL_MAXSIZE,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        s3 = S3Handler()
        gcs = GCSHandler()
        http = HTTPHandler(self._session)
        https = HTTPHandler(self._session, scheme="https")
        artifact = WBArtifactHandler()
        file_handler = LocalFileHandler()

        self._api = InternalApi()
        self._handler = MultiHandler(
            handlers=[s3, gcs, http, https, artifact, file_handler,],
            default_handler=TrackingHandler(),
        )

    def config(self):
        return self._config

    def load_file(self, artifact, name, manifest_entry):
        path, hit = self._cache.check_md5_obj_path(
            manifest_entry.digest, manifest_entry.size
        )
        if hit:
            return path
        response = self._session.get(
            self._file_url(self._api, artifact.entity, manifest_entry),
            auth=("api", self._api.api_key),
            stream=True,
        )
        response.raise_for_status()

        with util.fsync_open(path, "wb") as file:
            for data in response.iter_content(chunk_size=16 * 1024):
                file.write(data)
        return path

    def store_reference(
        self, artifact, path, name=None, checksum=True, max_objects=None
    ):
        return self._handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )

    def load_reference(self, artifact, name, manifest_entry, local=False):
        return self._handler.load_path(self._cache, manifest_entry, local)

    def _file_url(self, api, entity_name, manifest_entry):
        storage_layout = self._config.get("storageLayout", StorageLayout.V1)
        storage_region = self._config.get("storageRegion", "default")
        md5_hex = util.bytes_to_hex(base64.b64decode(manifest_entry.digest))

        if storage_layout == StorageLayout.V1:
            return "{}/artifacts/{}/{}".format(
                api.settings("base_url"), entity_name, md5_hex
            )
        elif storage_layout == StorageLayout.V2:
            return "{}/artifactsV2/{}/{}/{}/{}".format(
                api.settings("base_url"),
                storage_region,
                entity_name,
                quote(manifest_entry.birth_artifact_id),
                md5_hex,
            )
        else:
            raise Exception("unrecognized storage layout: {}".format(storage_layout))

    def store_file(
        self, artifact_id, artifact_manifest_id, entry, preparer, progress_callback=None
    ):
        # write-through cache
        cache_path, hit = self._cache.check_md5_obj_path(entry.digest, entry.size)
        if not hit:
            shutil.copyfile(entry.local_path, cache_path)

        resp = preparer.prepare(
            lambda: {
                "artifactID": artifact_id,
                "artifactManifestID": artifact_manifest_id,
                "name": entry.path,
                "md5": entry.digest,
            }
        )

        entry.birth_artifact_id = resp.birth_artifact_id
        exists = resp.upload_url is None
        if not exists:
            with open(entry.local_path, "rb") as file:
                # This fails if we don't send the first byte before the signed URL
                # expires.
                self._api.upload_file_retry(
                    resp.upload_url,
                    file,
                    progress_callback,
                    extra_headers={
                        header.split(":", 1)[0]: header.split(":", 1)[1]
                        for header in (resp.upload_headers or {})
                    },
                )
        return exists


# Don't use this yet!
class __S3BucketPolicy(StoragePolicy):
    @classmethod
    def name(cls):
        return "wandb-s3-bucket-policy-v1"

    @classmethod
    def from_config(cls, config):
        if "bucket" not in config:
            raise ValueError("Bucket name not found in config")
        return cls(config["bucket"])

    def __init__(self, bucket):
        self._bucket = bucket
        s3 = S3Handler(bucket)
        local = LocalFileHandler()

        self._handler = MultiHandler(
            handlers=[s3, local,], default_handler=TrackingHandler()
        )

    def config(self):
        return {"bucket": self._bucket}

    def load_path(self, artifact, manifest_entry, local=False):
        return self._handler.load_path(artifact, manifest_entry, local=local)

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        return self._handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )


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
        url = urlparse(manifest_entry.ref)
        if url.scheme not in self._handlers:
            if self._default_handler is not None:
                return self._default_handler.load_path(
                    artifact, manifest_entry, local=local
                )
            raise ValueError(
                'No storage handler registered for scheme "%s"' % url.scheme
            )
        return self._handlers[url.scheme].load_path(
            artifact, manifest_entry, local=local
        )

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        url = urlparse(path)
        if url.scheme not in self._handlers:
            if self._handlers is not None:
                return self._default_handler.store_path(
                    artifact,
                    path,
                    name=name,
                    checksum=checksum,
                    max_objects=max_objects,
                )
            raise ValueError(
                'No storage handler registered for scheme "%s"' % url.scheme
            )
        return self._handlers[url.scheme].store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )


class TrackingHandler(StorageHandler):
    def __init__(self, scheme=None):
        """
        Tracks paths as is, with no modification or special processing. Useful
        when paths being tracked are on file systems mounted at a standardized
        location.

        For example, if the data to track is located on an NFS share mounted on
        `/data`, then it is sufficient to just track the paths.
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
            url = urlparse(manifest_entry.ref)
            raise ValueError(
                "Cannot download file at path %s, scheme %s not recognized"
                % (manifest_entry.ref, url.scheme)
            )
        return manifest_entry.path

    def store_path(self, artifact, path, name=None, checksum=False, max_objects=None):
        url = urlparse(path)
        if name is None:
            raise ValueError(
                'You must pass name="<entry_name>" when tracking references with unknown schemes. ref: %s'
                % path
            )
        termwarn(
            "Artifact references with unsupported schemes cannot be checksummed: %s"
            % path
        )
        name = name or url.path[1:]  # strip leading slash
        return [ArtifactManifestEntry(name, path, digest=path)]


DEFAULT_MAX_OBJECTS = 10000


class LocalFileHandler(StorageHandler):
    """Handles file:// references"""

    def __init__(self, scheme=None):
        """
        Tracks files or directories on a local filesystem. Directories
        are expanded to create an entry for each file contained within.
        """
        self._scheme = scheme or "file"
        self._cache = get_artifacts_cache()

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        url = urlparse(manifest_entry.ref)
        local_path = "%s%s" % (url.netloc, url.path)
        if not os.path.exists(local_path):
            raise ValueError(
                "Local file reference: Failed to find file at path %s" % local_path
            )

        path, hit = self._cache.check_md5_obj_path(
            manifest_entry.digest, manifest_entry.size
        )
        if hit:
            return path

        md5 = md5_file_b64(local_path)
        if md5 != manifest_entry.digest:
            raise ValueError(
                "Local file reference: Digest mismatch for path %s: expected %s but found %s"
                % (local_path, manifest_entry.digest, md5)
            )

        util.mkdir_exists_ok(os.path.dirname(path))
        shutil.copy(local_path, path)
        return path

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        url = urlparse(path)
        local_path = "%s%s" % (url.netloc, url.path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        # We have a single file or directory
        # Note, we follow symlinks for files contained within the directory
        entries = []
        if not checksum:
            return [
                ArtifactManifestEntry(name or os.path.basename(path), path, digest=path)
            ]

        if os.path.isdir(local_path):
            i = 0
            start_time = time.time()
            termlog(
                'Generating checksum for up to %i files in "%s"...\n'
                % (max_objects, local_path),
                newline=False,
            )
            for root, _, files in os.walk(local_path):
                for sub_path in files:
                    i += 1
                    if i >= max_objects:
                        raise ValueError(
                            "Exceeded %i objects tracked, pass max_objects to add_reference"
                            % max_objects
                        )
                    physical_path = os.path.join(root, sub_path)
                    logical_path = os.path.relpath(physical_path, start=local_path)
                    if name is not None:
                        logical_path = os.path.join(name, logical_path)
                    entry = ArtifactManifestEntry(
                        logical_path,
                        os.path.join(path, logical_path),
                        size=os.path.getsize(physical_path),
                        digest=md5_file_b64(physical_path),
                    )
                    entries.append(entry)
            termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        elif os.path.isfile(local_path):
            name = name or os.path.basename(local_path)
            entry = ArtifactManifestEntry(
                name,
                path,
                size=os.path.getsize(local_path),
                digest=md5_file_b64(local_path),
            )
            entries.append(entry)
        else:
            # TODO: update error message if we don't allow directories.
            raise ValueError('Path "%s" must be a valid file or directory path' % path)
        return entries


class S3Handler(StorageHandler):
    def __init__(self, scheme=None):
        self._scheme = scheme or "s3"
        self._s3 = None
        self._versioning_enabled = None
        self._cache = get_artifacts_cache()

    @property
    def scheme(self):
        return self._scheme

    def init_boto(self):
        if self._s3 is not None:
            return self._s3
        boto3 = util.get_module(
            "boto3",
            required="s3:// references requires the boto3 library, run pip install wandb[aws]",
        )
        self._s3 = boto3.session.Session().resource(
            "s3",
            endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION"),
        )
        self._botocore = util.get_module("botocore")
        return self._s3

    def _parse_uri(self, uri):
        url = urlparse(uri)
        bucket = url.netloc
        key = url.path[1:]  # strip leading slash
        return bucket, key

    def versioning_enabled(self, bucket):
        self.init_boto()
        if self._versioning_enabled is not None:
            return self._versioning_enabled
        res = self._s3.BucketVersioning(bucket)
        self._versioning_enabled = res.status == "Enabled"
        return self._versioning_enabled

    def load_path(self, artifact, manifest_entry, local=False):
        if not local:
            return manifest_entry.ref

        path, hit = self._cache.check_etag_obj_path(
            manifest_entry.digest, manifest_entry.size
        )
        if hit:
            return path

        self.init_boto()
        bucket, key = self._parse_uri(manifest_entry.ref)
        version = manifest_entry.extra.get("versionID")

        extra_args = {}
        if version is None:
            # We don't have version information so just get the latest version
            # and fallback to listing all versions if we don't have a match.
            obj = self._s3.Object(bucket, key)
            etag = self._etag_from_obj(obj)
            if etag != manifest_entry.digest:
                if self.versioning_enabled(bucket):
                    # Fallback to listing versions
                    obj = None
                    object_versions = self._s3.Bucket(bucket).object_versions.filter(
                        Prefix=key
                    )
                    for object_version in object_versions:
                        if (
                            manifest_entry.extra.get("etag")
                            == object_version.e_tag[1:-1]
                        ):
                            obj = object_version.Object()
                            extra_args["VersionId"] = object_version.version_id
                            break
                    if obj is None:
                        raise ValueError(
                            "Couldn't find object version for %s/%s matching etag %s"
                            % (self._bucket, key, manifest_entry.extra.get("etag"))
                        )
                else:
                    raise ValueError(
                        "Digest mismatch for object %s: expected %s but found %s"
                        % (manifest_entry.ref, manifest_entry.digest, etag)
                    )
        else:
            obj = self._s3.ObjectVersion(bucket, key, version).Object()
            extra_args["VersionId"] = version

        obj.download_file(path, ExtraArgs=extra_args)
        return path

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        self.init_boto()
        bucket, key = self._parse_uri(path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        if not checksum:
            return [ArtifactManifestEntry(name or key, path, digest=path)]

        objs = [self._s3.Object(bucket, key)]
        start_time = None
        multi = False
        try:
            objs[0].load()
        except self._botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                multi = True
                start_time = time.time()
                termlog(
                    'Generating checksum for up to %i objects with prefix "%s"... '
                    % (max_objects, key),
                    newline=False,
                )
                objs = (
                    self._s3.Bucket(bucket)
                    .objects.filter(Prefix=key)
                    .limit(max_objects)
                )
            else:
                raise CommError(
                    "Unable to connect to S3 (%s): %s"
                    % (e.response["Error"]["Code"], e.response["Error"]["Message"])
                )

        # Weird iterator scoping makes us assign this to a local function
        size = self._size_from_obj
        entries = [
            self._entry_from_obj(obj, path, name, prefix=key, multi=multi)
            for obj in objs
            if size(obj) > 0
        ]
        if start_time is not None:
            termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        if len(entries) >= max_objects:
            raise ValueError(
                "Exceeded %i objects tracked, pass max_objects to add_reference"
                % max_objects
            )
        return entries

    def _size_from_obj(self, obj):
        # ObjectSummary has size, Object has content_length
        if hasattr(obj, "size"):
            size = obj.size
        else:
            size = obj.content_length
        return size

    def _entry_from_obj(self, obj, path, name=None, prefix="", multi=False):
        ref = path
        if name is None:
            if prefix in obj.key and prefix != obj.key:
                relpath = os.path.relpath(obj.key, start=prefix)
                name = relpath
                ref = os.path.join(path, relpath)
            else:
                name = os.path.basename(obj.key)
                ref = path
        elif multi:
            relpath = os.path.relpath(obj.key, start=prefix)
            name = os.path.join(name, relpath)
            ref = os.path.join(path, relpath)
        return ArtifactManifestEntry(
            name,
            ref,
            self._etag_from_obj(obj),
            size=self._size_from_obj(obj),
            extra=self._extra_from_obj(obj),
        )

    @staticmethod
    def _etag_from_obj(obj):
        return obj.e_tag[1:-1]  # escape leading and trailing quote

    @staticmethod
    def _extra_from_obj(obj):
        extra = {
            "etag": obj.e_tag[1:-1],  # escape leading and trailing quote
        }
        # ObjectSummary will never have version_id
        if hasattr(obj, "version_id") and obj.version_id != "null":
            extra["versionID"] = obj.version_id
        return extra

    @staticmethod
    def _content_addressed_path(md5):
        # TODO: is this the structure we want? not at all human
        # readable, but that's probably OK. don't want people
        # poking around in the bucket
        return "wandb/%s" % base64.b64encode(md5.encode("ascii")).decode("ascii")


class GCSHandler(StorageHandler):
    def __init__(self, scheme=None):
        self._scheme = scheme or "gs"
        self._client = None
        self._versioning_enabled = None
        self._cache = get_artifacts_cache()

    def versioning_enabled(self, bucket):
        if self._versioning_enabled is not None:
            return self._versioning_enabled
        self.init_gcs()
        bucket = self._client.bucket(bucket)
        bucket.reload()
        self._versioning_enabled = bucket.versioning_enabled
        return self._versioning_enabled

    @property
    def scheme(self):
        return self._scheme

    def init_gcs(self):
        if self._client is not None:
            return self._client
        storage = util.get_module(
            "google.cloud.storage",
            required="gs:// references requires the google-cloud-storage library, run pip install wandb[gcp]",
        )
        self._client = storage.Client()
        return self._client

    def _parse_uri(self, uri):
        url = urlparse(uri)
        bucket = url.netloc
        key = url.path[1:]
        return bucket, key

    def load_path(self, artifact, manifest_entry, local=False):
        if not local:
            return manifest_entry.ref

        path, hit = self._cache.check_md5_obj_path(
            manifest_entry.digest, manifest_entry.size
        )
        if hit:
            return path

        self.init_gcs()
        bucket, key = self._parse_uri(manifest_entry.ref)
        version = manifest_entry.extra.get("versionID")

        obj = None
        # First attempt to get the generation specified, this will return None if versioning is not enabled
        if version is not None:
            obj = self._client.bucket(bucket).get_blob(key, generation=version)

        if obj is None:
            # Object versioning is disabled on the bucket, so just get
            # the latest version and make sure the MD5 matches.
            obj = self._client.bucket(bucket).get_blob(key)
            if obj is None:
                raise ValueError(
                    "Unable to download object %s with generation %s"
                    % (manifest_entry.ref, version)
                )
            md5 = obj.md5_hash
            if md5 != manifest_entry.digest:
                raise ValueError(
                    "Digest mismatch for object %s: expected %s but found %s"
                    % (manifest_entry.ref, manifest_entry.digest, md5)
                )

        obj.download_to_filename(path)
        return path

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        self.init_gcs()
        bucket, key = self._parse_uri(path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS

        if not checksum:
            return [ArtifactManifestEntry(name or key, path, digest=path)]
        start_time = None
        obj = self._client.bucket(bucket).get_blob(key)
        multi = obj is None
        if multi:
            start_time = time.time()
            termlog(
                'Generating checksum for up to %i objects with prefix "%s"... '
                % (max_objects, key),
                newline=False,
            )
            objects = self._client.bucket(bucket).list_blobs(
                prefix=key, max_results=max_objects
            )
        else:
            objects = [obj]

        entries = [
            self._entry_from_obj(obj, path, name, prefix=key, multi=multi)
            for obj in objects
        ]
        if start_time is not None:
            termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        if len(entries) >= max_objects:
            raise ValueError(
                "Exceeded %i objects tracked, pass max_objects to add_reference"
                % max_objects
            )
        return entries

    def _entry_from_obj(self, obj, path, name=None, prefix="", multi=False):
        ref = path
        if name is None:
            if prefix in obj.name and prefix != obj.name:
                name = os.path.relpath(obj.name, start=prefix)
                ref = os.path.join(path, name)
            else:
                name = os.path.basename(obj.name)
        elif multi:
            # We're listing a path and user provided name, just prepend it
            name = os.path.join(name, os.path.basename(obj.name))
            ref = os.path.join(path, name)
        return ArtifactManifestEntry(
            name, ref, obj.md5_hash, size=obj.size, extra=self._extra_from_obj(obj)
        )

    @staticmethod
    def _extra_from_obj(obj):
        return {
            "etag": obj.etag,
            "versionID": obj.generation,
        }

    @staticmethod
    def _content_addressed_path(md5):
        # TODO: is this the structure we want? not at all human
        # readable, but that's probably OK. don't want people
        # poking around in the bucket
        return "wandb/%s" % base64.b64encode(md5.encode("ascii")).decode("ascii")


class HTTPHandler(StorageHandler):
    def __init__(self, session, scheme=None):
        self._scheme = scheme or "http"
        self._cache = get_artifacts_cache()
        self._session = session

    @property
    def scheme(self):
        return self._scheme

    def load_path(self, artifact, manifest_entry, local=False):
        if not local:
            return manifest_entry.ref

        path, hit = self._cache.check_etag_obj_path(
            manifest_entry.digest, manifest_entry.size
        )
        if hit:
            return path

        response = self._session.get(manifest_entry.ref, stream=True)
        response.raise_for_status()

        digest, size, extra = self._entry_from_headers(response.headers)
        digest = digest or path
        if manifest_entry.digest != digest:
            raise ValueError(
                "Digest mismatch for url %s: expected %s but found %s"
                % (manifest_entry.ref, manifest_entry.digest, digest)
            )

        with util.fsync_open(path, "wb") as file:
            for data in response.iter_content(chunk_size=16 * 1024):
                file.write(data)
        return path

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        name = name or os.path.basename(path)
        if not checksum:
            return [ArtifactManifestEntry(name, path, digest=path)]

        with self._session.get(path, stream=True) as response:
            response.raise_for_status()
            digest, size, extra = self._entry_from_headers(response.headers)
            digest = digest or path
        return [
            ArtifactManifestEntry(name, path, digest=digest, size=size, extra=extra)
        ]

    def _entry_from_headers(self, headers):
        response_headers = {k.lower(): v for k, v in headers.items()}
        size = response_headers.get("content-length", None)
        if size:
            size = int(size)

        digest = response_headers.get("etag", None)
        extra = {}
        if digest:
            extra["etag"] = digest
        if digest and digest[:1] == '"' and digest[-1:] == '"':
            digest = digest[1:-1]  # trim leading and trailing quotes around etag
        return digest, size, extra


class WBArtifactHandler(StorageHandler):
    """Handles loading and storing Artifact reference-type files"""

    def __init__(self, scheme=None):
        self._scheme = scheme or "wandb-artifact"
        self._cache = get_artifacts_cache()
        self._client = None

    @property
    def scheme(self):
        """overrides parent scheme

        Returns:
            (str): The scheme to which this handler applies.
        """
        return self._scheme

    @property
    def client(self):
        if self._client is None:
            self._client = PublicApi()
        return self._client

    def load_path(self, artifact, manifest_entry, local=False):
        """
        Loads the file within the specified artifact given its
        corresponding entry. In this case, the referenced artifact is downloaded
        and a new symlink is created and returned to the caller.

        Arguments:
            manifest_entry (ArtifactManifestEntry): The index entry to load

        Returns:
            (os.PathLike): A path to the file represented by `index_entry`
        """
        # We don't check for cache hits here. Since we have 0 for size (since this
        # is a cross-artifact reference which and we've made the choice to store 0
        # in the size field), we can't confirm if the file is complete. So we just
        # rely on the dep_artifact entry's download() method to do its own cache
        # check.

        # Parse the reference path and download the artifact if needed
        artifact_id = util.host_from_path(manifest_entry.ref)
        artifact_file_path = util.uri_from_path(manifest_entry.ref)

        dep_artifact = PublicArtifact.from_id(
            util.hex_to_b64_id(artifact_id), self.client
        )
        if local:
            link_target_path = dep_artifact.get_path(artifact_file_path).download()
        else:
            link_target_path = dep_artifact.get_path(artifact_file_path).ref()

        return link_target_path

    def store_path(self, artifact, path, name=None, checksum=True, max_objects=None):
        """
        Stores the file or directory at the given path within the specified artifact. In this
        case we recursively resolve the reference until the result is a concrete asset so that
        we don't have multiple hops. TODO-This resolution could be done in the server for
        performance improvements.

        Arguments:
            artifact: The artifact doing the storing
            path (str): The path to store
            name (str): If specified, the logical name that should map to `path`

        Returns:
            (list[ArtifactManifestEntry]): A list of manifest entries to store within the artifact
        """

        # Recursively resolve the reference until a concrete asset is found
        while path is not None and urlparse(path).scheme == self._scheme:
            artifact_id = util.host_from_path(path)
            artifact_file_path = util.uri_from_path(path)
            target_artifact = PublicArtifact.from_id(
                util.hex_to_b64_id(artifact_id), self.client
            )

            # this should only have an effect if the user added the reference by url
            # string directly (in other words they did not already load the artifact into ram.)
            target_artifact._load_manifest()

            entry = target_artifact._manifest.get_entry_by_path(artifact_file_path)
            path = entry.ref

        # Create the path reference
        path = "wandb-artifact://{}/{}".format(
            util.b64_to_hex_id(target_artifact.id), artifact_file_path
        )

        # Return the new entry
        return [
            ArtifactManifestEntry(
                name or os.path.basename(path), path, size=0, digest=entry.digest,
            )
        ]
