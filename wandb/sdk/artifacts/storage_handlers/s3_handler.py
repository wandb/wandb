"""S3 storage handler."""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlparse

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Never, Self

import wandb
from wandb import util
from wandb._strutils import ensureprefix
from wandb.errors import CommError
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr
from wandb.util import logger

from ._timing import TimedIf

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    # We could probably use https://pypi.org/project/boto3-stubs/ or something
    # instead of `type:ignore`ing these boto imports, but it's nontrivial:
    # for some reason, despite being actively maintained as of 2022-09-30,
    # the latest release of boto3-stubs doesn't include all the features we use.
    import boto3  # type: ignore
    import boto3.resources.base  # type: ignore
    import boto3.s3  # type: ignore
    import boto3.session  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


def _handle_import_error(exc: ImportError) -> Never:
    # We handle the ImportError this way for continuity/backward compatibility, but
    # consider a future, albeit breaking, change that just raises a proper `ImportError`.
    logger.exception(f"Error importing optional module {exc.name!r}")
    raise wandb.Error(
        "s3:// references require the boto3 library, run pip install wandb[aws]"
    )


@pydantic_dataclass
class _S3Path:
    """A parsed S3 path."""

    bucket: str
    key: str
    version: str | None

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        url = urlparse(uri)
        params = dict(parse_qsl(url.query))
        return cls(
            bucket=url.netloc,
            key=url.path.lstrip("/"),  # trim leading slash
            version=params.get("versionId"),
        )


class S3Handler(StorageHandler):
    _scheme: str
    _cache: ArtifactFileCache
    _s3: boto3.resources.base.ServiceResource | None

    def __init__(self, scheme: str = "s3") -> None:
        self._scheme = scheme
        self._cache = get_artifact_file_cache()
        self._s3 = None

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def init_boto(self) -> boto3.resources.base.ServiceResource:
        if self._s3 is not None:
            return self._s3

        try:
            import boto3
        except ImportError as e:
            _handle_import_error(e)

        from botocore.client import Config  # type: ignore

        s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL")
        s3_config = (
            Config(s3={"addressing_style": "virtual"})
            if s3_endpoint and self._is_coreweave_endpoint(s3_endpoint)
            else None
        )
        self._s3 = boto3.session.Session().resource(
            "s3",
            endpoint_url=s3_endpoint,
            region_name=os.getenv("AWS_REGION"),
            config=s3_config,
        )
        self._botocore = util.get_module("botocore")
        return self._s3

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

        path, hit, cache_open = self._cache.check_etag_obj_path(
            ref_uri,
            expected_digest,
            manifest_entry.size or 0,
        )
        if hit:
            return path

        s3 = self.init_boto()
        s3path = _S3Path.from_uri(ref_uri)

        try:
            if (version := manifest_entry.extra.get("versionID")) is not None:
                obj_version = s3.ObjectVersion(s3path.bucket, s3path.key, version)

                obj = obj_version.Object()
                etag = obj_version.head()["ETag"].strip('"')  # trim enclosing quotes
                extra_args = {"VersionId": version}
            else:
                obj = s3.Object(s3path.bucket, s3path.key)
                etag = obj.e_tag.strip('"')  # trim enclosing quotes
                extra_args = {}

        except self._botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                msg = f"Unable to find {manifest_entry.path} at s3://{s3path.bucket}/{s3path.key}"
                raise FileNotFoundError(msg) from e
            raise

        if etag != expected_digest:
            # Try to match the etag with some other version.
            if version:
                raise ValueError(
                    f"Digest mismatch for object {ref_uri!r} with version {version!r}: expected {expected_digest!r} but found {etag!r}"
                )

            object_versions = s3.Bucket(s3path.bucket).object_versions.filter(
                Prefix=s3path.key
            )
            expected_etag = manifest_entry.extra.get("etag")

            try:
                obj = next(
                    objv.Object()
                    for objv in object_versions
                    if expected_etag == objv.e_tag.strip('"')
                )
            except StopIteration:
                raise FileNotFoundError(
                    f"Couldn't find object version for {s3path.bucket}/{s3path.key} matching etag {expected_etag!r}"
                ) from None
            else:
                extra_args["VersionId"] = obj.version_id

        with cache_open(mode="wb") as f:
            obj.download_fileobj(f, ExtraArgs=extra_args)
        return path

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        s3 = self.init_boto()

        # The passed in path might have query string parameters.
        # We only need to care about a subset, like version, when
        # parsing. Once we have that, we can store the rest of the
        # metadata in the artifact entry itself.
        s3path = _S3Path.from_uri(path)

        path = f"{self._scheme}://{s3path.bucket}/{s3path.key}"

        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        if not checksum:
            entry_path = name or s3path.key or s3path.bucket
            return [ArtifactManifestEntry(path=entry_path, ref=path, digest=path)]

        # If an explicit version is specified, use that. Otherwise, use the head version.
        objs = [
            s3.ObjectVersion(s3path.bucket, s3path.key, s3path.version).Object()
            if s3path.version
            else s3.Object(s3path.bucket, s3path.key)
        ]
        multi = False
        if s3path.key:
            try:
                objs[0].load()
                # S3 lacks true folders, but a folder key can reference a valid
                # file, which prevents recursive uploads. Check whether the
                # object's metadata marks it as a directory and perform a
                # multi-file upload if so.
                if "x-directory" in objs[0].content_type:
                    multi = True
            except self._botocore.exceptions.ClientError as e:
                if (errinfo := e.response.get("Error")) and (errinfo["Code"] == "404"):
                    multi = True
                elif errinfo:
                    raise CommError(
                        f"Unable to connect to S3 ({errinfo['Code']}): {errinfo['Message']}. "
                        "Check that your authentication credentials are valid "
                        "and that your region is set correctly."
                    )
                else:
                    raise
        else:
            multi = True

        with TimedIf(multi):
            if multi:
                termlog(
                    f'Generating checksum for up to {max_objects} objects in "{s3path.bucket}/{s3path.key}"... ',
                    newline=False,
                )
                bucket_objs = s3.Bucket(s3path.bucket).objects
                if s3path.key:
                    objs = bucket_objs.filter(Prefix=s3path.key).limit(max_objects)
                else:
                    objs = bucket_objs.limit(max_objects)
            # Weird iterator scoping makes us assign this to a local function
            getsize = self._size_from_obj
            entries = [
                self._entry_from_obj(obj, path, name, prefix=s3path.key, multi=multi)
                for obj in objs
                if getsize(obj) > 0
            ]
            if len(entries) > max_objects:
                raise ValueError(
                    f"Exceeded {max_objects} objects tracked, pass max_objects to add_reference"
                )
            return entries

    @staticmethod
    def _size_from_obj(obj: boto3.s3.Object | boto3.s3.ObjectSummary) -> int:
        # ObjectSummary has size, Object has content_length
        size = getattr(obj, "size", None)
        return obj.content_length if (size is None) else size

    def _entry_from_obj(
        self,
        obj: boto3.s3.Object | boto3.s3.ObjectSummary,
        path: str,
        name: StrPath | None = None,
        prefix: str = "",
        multi: bool = False,
    ) -> ArtifactManifestEntry:
        """Create an ArtifactManifestEntry from an S3 object.

        Args:
            obj: The S3 object
            path: The S3-style path (e.g.: "s3://bucket/file.txt")
            name: The user assigned name, or None if not specified
            prefix: The prefix to add (will be the same as `path` for directories)
            multi: Whether or not this is a multi-object add.
        """
        s3path = _S3Path.from_uri(path)

        # Always use posix paths, since that's what S3 uses.
        posix_key = PurePosixPath(obj.key)  # the bucket key
        posix_path = PurePosixPath(s3path.bucket, s3path.key)  # path without the scheme
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
            ref=f"{self._scheme}://{posix_ref}",
            digest=obj.e_tag.strip('"'),
            size=self._size_from_obj(obj),
            extra=self._extra_from_obj(obj),
        )

    def _extra_from_obj(
        self, obj: boto3.s3.Object | boto3.s3.ObjectSummary
    ) -> dict[str, str]:
        extra = {"etag": obj.e_tag.strip('"')}  # trim leading and trailing quote
        if not hasattr(obj, "version_id"):
            # Convert ObjectSummary to Object to get the version_id.
            obj = self._s3.Object(obj.bucket_name, obj.key)  # type: ignore[union-attr]

        if (version_id := getattr(obj, "version_id", None)) and (version_id != "null"):
            extra["versionID"] = version_id

        return extra

    _CW_LEGACY_NETLOC_REGEX: re.Pattern[str] = re.compile(
        r"""
        # accelerated endpoints like "accel-object.<region>.coreweave.com"
        accel-object\.[a-z0-9-]+\.coreweave\.com
        |
        # URLs like "object.<region>.coreweave.com"
        object\.[a-z0-9-]+\.coreweave\.com
        """,
        flags=re.VERBOSE,
    )

    def _is_coreweave_endpoint(self, endpoint_url: str) -> bool:
        if not (url := endpoint_url.strip().rstrip("/")):
            return False

        # Only http://cwlota.com is supported using HTTP
        if url == "http://cwlota.com":
            return True

        # Enforce HTTPS otherwise
        https_url = ensureprefix(url, "https://")
        netloc = urlparse(https_url).netloc
        return bool(
            # Match for https://cwobject.com
            (netloc == "cwobject.com")
            or
            # Check for legacy endpoints
            self._CW_LEGACY_NETLOC_REGEX.fullmatch(netloc)
        )
