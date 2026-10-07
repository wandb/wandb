"""GCS storage handler."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Optional
from urllib.parse import ParseResult, urlparse

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Never, Self

import wandb
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr
from wandb.util import logger

from ._timing import TimedIf

if TYPE_CHECKING:
    from google.cloud import storage  # type: ignore[import-not-found, import-untyped]

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


class _GCSIsADirectoryError(Exception):
    """Raised when we try to download a GCS folder."""


def _handle_import_error(exc: ImportError) -> Never:
    # We handle the ImportError this way for continuity/backward compatibility, but
    # consider a future, albeit breaking, change that just raises a proper `ImportError`.
    logger.exception(f"Error importing optional module {exc.name!r}")
    raise wandb.Error(
        "gs:// references require the google-cloud-storage library, run pip install wandb[gcp]"
    )


@pydantic_dataclass
class _GCSPath:
    """A parsed GCS path."""

    bucket: str
    key: str
    version: Optional[str]  # noqa: UP045

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Parse a GCS URI into a bucket, key, and optional version."""
        parsed = urlparse(uri)
        return cls(
            bucket=parsed.netloc,
            key=parsed.path.lstrip("/"),
            version=parsed.fragment or None,
        )


class GCSHandler(StorageHandler):
    _scheme: str
    _client: storage.Client | None
    _cache: ArtifactFileCache

    def __init__(self, scheme: str = "gs") -> None:
        self._scheme = scheme
        self._client = None
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def init_gcs(self) -> storage.Client:
        if self._client is not None:
            return self._client

        try:
            from google.cloud import storage
        except ImportError as e:
            _handle_import_error(e)

        self._client = storage.Client()
        return self._client

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if (ref_uri := manifest_entry.ref) is None:
            raise ValueError("Missing reference path/URI on artifact manifest entry")
        if not local:
            return ref_uri

        expected_digest = manifest_entry.digest
        expected_size = manifest_entry.size

        path, hit, cache_open = self._cache.check_etag_obj_path(
            url=ref_uri, etag=expected_digest, size=expected_size or 0
        )
        if hit:
            return path

        client = self.init_gcs()

        gcs_path = _GCSPath.from_uri(ref_uri)
        bucket = client.bucket(gcs_path.bucket)

        # Skip downloading an entry that corresponds to a folder
        if _is_dir(bucket, gcs_path.key, expected_size):
            raise _GCSIsADirectoryError(
                f"Unable to download GCS folder {ref_uri!r}, skipping"
            )

        # Try, in order:
        obj = (
            # First attempt to get the generation (specific version), if specified.
            # Will return None if versioning is disabled.
            (
                (version_id := manifest_entry.extra.get("versionID")) is not None
                and bucket.get_blob(gcs_path.key, generation=version_id)
            )
            or
            # Object versioning is disabled on the bucket, or versionID isn't available,
            # so just get the latest version and make sure the MD5 matches.
            bucket.get_blob(gcs_path.key)
        )

        if obj is None:
            raise ValueError(
                f"Unable to download object {ref_uri!r} with generation {version_id!r}"
            )

        if (digest := obj.etag) != expected_digest:
            raise ValueError(
                f"Digest mismatch for object {ref_uri!r}: expected {expected_digest!r} but found {digest!r}"
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
    ) -> list[ArtifactManifestEntry]:
        client = self.init_gcs()

        # After parsing any query params / fragments for additional context,
        # such as version identifiers, pare down the path to just the bucket
        # and key.
        gcs_path = _GCSPath.from_uri(path)
        path = f"{self._scheme}://{gcs_path.bucket}/{gcs_path.key}"
        max_objects = max_objects or DEFAULT_MAX_OBJECTS

        if not checksum:
            return [
                ArtifactManifestEntry(path=name or gcs_path.key, ref=path, digest=path)
            ]

        bucket = client.bucket(gcs_path.bucket)
        try:
            from google.api_core.exceptions import Forbidden
        except ImportError as e:
            _handle_import_error(e)

        try:
            obj = bucket.get_blob(gcs_path.key, generation=gcs_path.version)
        except Forbidden:
            # The caller has `storage.objects.list` but not `storage.objects.get`.
            # A 403 says nothing about whether the key exists or whether it is a
            # file or a folder, so resolve that with list calls instead.
            return self._store_path_via_list(bucket, gcs_path, path, name, max_objects)

        if (obj is None) and (gcs_path.version is not None):
            raise ValueError(f"Object does not exist: {path}#{gcs_path.version}")

        # HNS buckets store directory markers as blobs, so check the blob name
        # to see if it represents a directory.
        with TimedIf(multi := ((obj is None) or obj.name.endswith("/"))):
            if multi:
                termlog(
                    f"Generating checksum for up to {max_objects} objects with prefix {gcs_path.key!r}... ",
                    newline=False,
                )
                objects = bucket.list_blobs(
                    prefix=gcs_path.key, max_results=max_objects
                )
            else:
                objects = [obj]

            entries = [
                self._entry_from_obj(obj, path, name, prefix=gcs_path.key, multi=multi)
                for obj in objects
                if obj and not obj.name.endswith("/")
            ]

        if len(entries) > max_objects:
            raise ValueError(
                f"Exceeded {max_objects!r} objects tracked, pass max_objects to add_reference"
            )

        return entries

    def _store_path_via_list(
        self,
        bucket: storage.Bucket,
        gcs_path: _GCSPath,
        path: str,
        name: StrPath | None,
        max_objects: int,
    ) -> list[ArtifactManifestEntry]:
        """Resolve a reference using only `storage.objects.list`.

        Used when `get_blob` is forbidden. Produces the same entries as the
        `get_blob` path for references that path handles correctly.
        """
        try:
            from google.api_core.exceptions import Forbidden
        except ImportError as e:
            _handle_import_error(e)

        key = gcs_path.key

        version: int | None = None
        if gcs_path.version is not None:
            try:
                version = int(gcs_path.version)
            except ValueError:
                raise ValueError(
                    f"Version fragment must be an integer generation: {path}#{gcs_path.version}"
                ) from None

        def list_folder(prefix: str) -> tuple[int, list[ArtifactManifestEntry]]:
            # `list_blobs` is lazy and makes HTTP requests while it is iterated,
            # so consume it here and build entries as blobs stream by.
            with TimedIf(True):
                termlog(
                    f"Generating checksum for up to {max_objects} objects with prefix {prefix!r}... ",
                    newline=False,
                )
                n_raw = 0
                entries: list[ArtifactManifestEntry] = []
                for blob in bucket.list_blobs(prefix=prefix, max_results=max_objects):
                    n_raw += 1
                    # Directory markers are blobs whose names end in "/".
                    if not blob.name.endswith("/"):
                        entries.append(
                            self._entry_from_obj(
                                blob, path, name, prefix=key, multi=True
                            )
                        )
                return n_raw, entries

        if key.endswith("/"):
            if version is not None:
                raise ValueError(
                    f"Version fragment is not valid on a folder reference: {path}#{gcs_path.version}"
                )
            _, entries = list_folder(key)
            return entries

        if version is None:
            # The exact key is the lexicographically smallest name with that
            # prefix, so one result tells us whether the file exists, and
            # distinguishes `data` (file) from `data/` (marker) and
            # `data-1.txt` (sibling).
            try:
                first = next(iter(bucket.list_blobs(prefix=key, max_results=1)), None)
            except Forbidden:
                # List permission scoped to a managed folder `key/` denies the
                # bare prefix `key`. Treat the exact object as unresolved and
                # try the folder; if that is forbidden too, it propagates.
                first = None

            if first is not None and first.name == key:
                return [
                    self._entry_from_obj(first, path, name, prefix=key, multi=False)
                ]
            n_raw, entries = list_folder(key + "/")
            if n_raw == 0 and first is not None:
                # Something matches the string prefix, but nothing is `key` or
                # under `key/`: a partial filename prefix such as "train-" over
                # "train-0" and "train-1".
                raise ValueError(f"{path!r} is neither an object nor a folder prefix")
            return entries

        # All generations of `key` sort before any longer name.
        for blob in bucket.list_blobs(prefix=key, versions=True):
            if blob.name != key:
                break
            if blob.generation == version:
                return [self._entry_from_obj(blob, path, name, prefix=key, multi=False)]
        raise ValueError(f"Object does not exist: {path}#{gcs_path.version}")

    def _entry_from_obj(
        self,
        obj: storage.Blob,
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
        uri = _GCSPath.from_uri(path)

        # Always use posix paths, since that's what S3 uses.
        posix_key = PurePosixPath(obj.name)  # the bucket key
        posix_path = PurePosixPath(uri.bucket, uri.key)  # path without the scheme
        posix_prefix = PurePosixPath(prefix)  # the prefix, if adding a prefix

        if name is None:
            # We're adding a directory (prefix), so calculate a relative path.
            if posix_prefix in posix_key.parents:
                posix_name = posix_key.relative_to(posix_prefix)
                posix_ref = posix_path / posix_name
            else:
                posix_name = PurePosixPath(posix_key.name)
                posix_ref = posix_path

        elif multi:
            # We're adding a directory with a name override.
            relpath = posix_key.relative_to(posix_prefix)
            posix_name = PurePosixPath(name) / relpath
            posix_ref = posix_path / relpath

        else:
            posix_name = PurePosixPath(name or "")
            posix_ref = posix_path

        return ArtifactManifestEntry(
            path=posix_name,
            ref=f"{self._scheme}://{posix_ref}",
            digest=obj.etag,
            size=obj.size,
            extra={"versionID": obj.generation},
        )


def _is_dir(bucket: storage.Bucket, key: str, entry_size: int | None) -> bool:
    # A GCS folder key should end with a forward slash, but older manifest
    # entries may omit it. To detect folders, check the size and extension,
    # ensure there is no file with this reference, and confirm that the
    # slash-suffixed reference exists as a folder in GCS.
    return key.endswith("/") or (
        not (entry_size or PurePosixPath(key).suffix)
        and bucket.get_blob(key) is None
        and bucket.get_blob(f"{key}/") is not None
    )
