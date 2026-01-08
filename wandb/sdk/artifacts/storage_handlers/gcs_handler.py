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
    from google.cloud import storage  # type: ignore[import-not-found]

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
        # google-cloud-storage is optional dependency that requires
        # pip install wandb[gcp]. Importing these modules at top of file
        # breaks users doing pip install wandb without [gcp].
        from google.api_core.exceptions import (  # type: ignore[import-not-found]
            GoogleAPICallError,
        )
        from google.auth.exceptions import (  # type: ignore[import-not-found]
            GoogleAuthError,
        )

        client = self.init_gcs()

        # After parsing any query params / fragments for additional context,
        # such as version identifiers, pare down the path to just the bucket
        # and key.
        # For example: gs://my-bucket/my_object.pb#2
        # - bucket: my-bucket
        # - key: my_object.pb
        # - version: 2
        gcs_path = _GCSPath.from_uri(path)
        path = f"{self._scheme}://{gcs_path.bucket}/{gcs_path.key}"
        max_objects = max_objects or DEFAULT_MAX_OBJECTS

        if not checksum:
            return [
                ArtifactManifestEntry(path=name or gcs_path.key, ref=path, digest=path)
            ]

        bucket = client.bucket(gcs_path.bucket)

        # Try list_blobs first. Fallback to get_blob for backward compatibility.
        # Using get_blob is a valid use case for public buckets.
        # anonymous credentials on public buckets only allows get_blob without list_blobs.
        #
        # For our system test, the error comes from anonymous credentials:
        # google.auth.exceptions.InvalidOperation:
        # Anonymous credentials cannot be refreshed
        # For blob client, all the exceptions on operations are based on:
        # google.api_core.exceptions.GoogleAPICallError
        #
        # The fallback can lead to unnessary retries when user does not
        # have either get or list permission. The performance penalty is limited
        # because _store_path_via_get only get at most one file.
        try:
            return self._store_path_via_list(bucket, gcs_path, path, name, max_objects)
        except (GoogleAuthError, GoogleAPICallError) as e:
            logger.warning(f"list_blobs failed, falling back to get_blob: {e}")
            return self._store_path_via_get(bucket, gcs_path, path, name)

    def _store_path_via_list(
        self,
        bucket: storage.Bucket,
        gcs_path: _GCSPath,
        path: str,
        name: StrPath | None,
        max_objects: int,
    ) -> list[ArtifactManifestEntry]:
        with TimedIf(enabled=True):
            # Return different versions as blobs if user specified a version
            # https://cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.client.Client#google_cloud_storage_client_Client_list_blobs
            objects = bucket.list_blobs(
                prefix=gcs_path.key,
                max_results=max_objects,
                versions=gcs_path.version is not None,
            )

            entries = [
                self._entry_from_obj(obj, path, name, prefix=gcs_path.key)
                for obj in objects
                if obj
                # Skip folder
                and not obj.name.endswith("/")
                # When version specified, require exact key match (old get_blob behavior)
                # to avoid matching file that only matches the prefix.
                and (
                    gcs_path.version is not None
                    or (
                        str(obj.generation) == gcs_path.version
                        and obj.name == gcs_path.key
                    )
                )
            ]

        if len(entries) > 1:
            termlog(f"Added {len(entries)} objects with prefix {gcs_path.key!r}")

        # Error if versioned object doesn't exist
        if gcs_path.version is not None and len(entries) == 0:
            raise ValueError(f"Object does not exist: {path}#{gcs_path.version}")

        if len(entries) > max_objects:
            raise ValueError(
                f"Exceeded {max_objects!r} objects tracked, pass max_objects to add_reference"
            )

        return entries

    def _store_path_via_get(
        self,
        bucket: storage.Bucket,
        gcs_path: _GCSPath,
        path: str,
        name: StrPath | None,
    ) -> list[ArtifactManifestEntry]:
        obj = bucket.get_blob(gcs_path.key, generation=gcs_path.version)

        if obj is None and gcs_path.version is not None:
            raise ValueError(f"Object does not exist: {path}#{gcs_path.version}")

        if obj is None:
            # Object doesn't exist or it is a folder.
            # We cannot list files because we already called list_blobs
            # before get_blob in _store_path_via_list.
            return []

        # Filter out directory markers with empty blob
        if obj.name and obj.name.endswith("/"):
            return []

        # Single object found
        return [self._entry_from_obj(obj, path, name, prefix=gcs_path.key)]

    def _entry_from_obj(
        self,
        obj: storage.Blob,
        path: str,
        name: StrPath | None = None,
        prefix: str = "",
    ) -> ArtifactManifestEntry:
        """Create an ArtifactManifestEntry from a GCS object.

        Args:
            obj: The GCS object
            path: The GCS-style path (e.g.: "gs://bucket/file.txt")
            name: The user assigned name, or None if not specified
            prefix: The prefix used for listing (same as key for single files)
        """
        uri = _GCSPath.from_uri(path)

        # Always use posix paths, since that's what S3 uses.
        posix_key = PurePosixPath(obj.name)  # the bucket key
        posix_path = PurePosixPath(uri.bucket, uri.key)  # path without the scheme
        posix_prefix = PurePosixPath(prefix)  # the prefix used for listing

        # Check if this object is under a directory prefix
        is_under_prefix = posix_prefix in posix_key.parents

        if name is None:
            if is_under_prefix:
                # Object is under a directory prefix, use relative path
                posix_name = posix_key.relative_to(posix_prefix)
                posix_ref = posix_path / posix_name
            else:
                # Single file, use just the filename
                posix_name = PurePosixPath(posix_key.name)
                posix_ref = posix_path
        # FIXME: This breaks when the prefix is not a folder
        # also same code is copy pased in s3_hander.py
        # azure_handler.py actuall have different logic and has
        # external contribution in https://github.com/wandb/wandb/pull/7876/changes
        elif is_under_prefix:
            # Directory with custom name override
            relpath = posix_key.relative_to(posix_prefix)
            posix_name = PurePosixPath(name) / relpath
            posix_ref = posix_path / relpath
        else:
            # Single file with custom name
            posix_name = PurePosixPath(name)
            posix_ref = posix_path

        return ArtifactManifestEntry(
            path=posix_name,
            ref=f"{self._scheme}://{posix_ref}",
            digest=obj.etag,
            size=obj.size,
            # NOTE: gcs returns int for generation
            # https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob#google_cloud_storage_blob_Blob_generation
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
