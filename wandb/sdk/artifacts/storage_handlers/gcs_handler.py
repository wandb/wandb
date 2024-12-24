"""GCS storage handler."""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Sequence
from urllib.parse import ParseResult, urlparse

from wandb import util
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import google.cloud.storage as gcs_module  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact


class _GCSIsADirectoryError(Exception):
    """Raised when we try to download a GCS folder."""


class GCSHandler(StorageHandler):
    _client: gcs_module.client.Client | None

    def __init__(self, scheme: str | None = None) -> None:
        self._scheme = scheme or "gs"
        self._client = None
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def init_gcs(self) -> gcs_module.client.Client:
        if self._client is not None:
            return self._client
        storage = util.get_module(
            "google.cloud.storage",
            required="gs:// references requires the google-cloud-storage library, run pip install wandb[gcp]",
        )
        self._client = storage.Client()
        return self._client

    def _parse_uri(self, uri: str) -> tuple[str, str, str | None]:
        url = urlparse(uri)
        bucket = url.netloc
        key = url.path[1:]
        version = url.fragment if url.fragment else None
        return bucket, key, version

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        assert manifest_entry.ref is not None
        if not local:
            return manifest_entry.ref

        path, hit, cache_open = self._cache.check_etag_obj_path(
            url=URIStr(manifest_entry.ref),
            etag=ETag(manifest_entry.digest),
            size=manifest_entry.size if manifest_entry.size is not None else 0,
        )
        if hit:
            return path

        self.init_gcs()
        assert self._client is not None  # mypy: unwraps optionality
        assert manifest_entry.ref is not None
        bucket, key, _ = self._parse_uri(manifest_entry.ref)
        version = manifest_entry.extra.get("versionID")

        if self._is_dir(manifest_entry):
            raise _GCSIsADirectoryError(
                f"Unable to download GCS folder {manifest_entry.ref!r}, skipping"
            )

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
                    f"Unable to download object {manifest_entry.ref} with generation {version}"
                )
            if obj.etag != manifest_entry.digest:
                raise ValueError(
                    f"Digest mismatch for object {manifest_entry.ref}: "
                    f"expected {manifest_entry.digest} but found {obj.etag}"
                )

        with cache_open(mode="wb") as f:
            obj.download_to_file(f)
        return path

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        self.init_gcs()
        assert self._client is not None  # mypy: unwraps optionality

        # After parsing any query params / fragments for additional context,
        # such as version identifiers, pare down the path to just the bucket
        # and key.
        bucket, key, version = self._parse_uri(path)
        path = URIStr(f"{self._scheme}://{bucket}/{key}")
        max_objects = max_objects or DEFAULT_MAX_OBJECTS

        if not checksum:
            return [ArtifactManifestEntry(path=name or key, ref=path, digest=path)]

        start_time = None
        obj = self._client.bucket(bucket).get_blob(key, generation=version)
        if obj is None and version is not None:
            raise ValueError(f"Object does not exist: {path}#{version}")
        multi = obj is None
        if multi:
            start_time = time.time()
            termlog(
                f'Generating checksum for up to {max_objects} objects with prefix "{key}"... ',
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
            if not obj.name.endswith("/")
        ]
        if start_time is not None:
            termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        if len(entries) > max_objects:
            raise ValueError(
                f"Exceeded {max_objects} objects tracked, pass max_objects to add_reference"
            )
        return entries

    def _entry_from_obj(
        self,
        obj: gcs_module.blob.Blob,
        path: str,
        name: StrPath | None = None,
        prefix: str = "",
        multi: bool = False,
    ) -> ArtifactManifestEntry:
        """Create an ArtifactManifestEntry from a GCS object.

        Args:
            obj: The GCS object
            path: The GCS-style path (e.g.: "gs://bucket/file.txt")
            name: The user assigned name, or None if not specified
            prefix: The prefix to add (will be the same as `path` for directories)
            multi: Whether or not this is a multi-object add.
        """
        bucket, key, _ = self._parse_uri(path)

        # Always use posix paths, since that's what S3 uses.
        posix_key = PurePosixPath(obj.name)  # the bucket key
        posix_path = PurePosixPath(bucket) / PurePosixPath(
            key
        )  # the path, with the scheme stripped
        posix_prefix = PurePosixPath(prefix)  # the prefix, if adding a prefix
        posix_name = PurePosixPath(name or "")
        posix_ref = posix_path

        if name is None:
            # We're adding a directory (prefix), so calculate a relative path.
            if str(posix_prefix) in str(posix_key) and posix_prefix != posix_key:
                posix_name = posix_key.relative_to(posix_prefix)
                posix_ref = posix_path / posix_name
            else:
                posix_name = PurePosixPath(posix_key.name)
                posix_ref = posix_path
        elif multi:
            # We're adding a directory with a name override.
            relpath = posix_key.relative_to(posix_prefix)
            posix_name = posix_name / relpath
            posix_ref = posix_path / relpath
        return ArtifactManifestEntry(
            path=posix_name,
            ref=URIStr(f"{self._scheme}://{str(posix_ref)}"),
            digest=obj.etag,
            size=obj.size,
            extra={"versionID": obj.generation},
        )

    def _is_dir(
        self,
        manifest_entry: ArtifactManifestEntry,
    ) -> bool:
        assert self._client is not None
        assert manifest_entry.ref is not None
        bucket, key, _ = self._parse_uri(manifest_entry.ref)
        bucket_obj = self._client.bucket(bucket)
        # A gcs bucket key should end with a forward slash on gcloud, but
        # we save these refs without the forward slash in the manifest entry
        # so we check the size and extension, make sure its not referring to
        # an actual file with this reference, and that the ref with the slash
        # exists on gcloud
        return key.endswith("/") or (
            not (manifest_entry.size or PurePosixPath(key).suffix)
            and bucket_obj.get_blob(key) is None
            and bucket_obj.get_blob(f"{key}/") is not None
        )
