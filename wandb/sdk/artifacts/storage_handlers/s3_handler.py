"""S3 storage handler."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qsl, urlparse

from wandb import __version__ as _wandb_version
from wandb import util
from wandb._strutils import ensureprefix
from wandb.errors import CommError
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

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
        boto: boto3 = util.get_module(
            "boto3",
            required="s3:// references requires the boto3 library, run pip install wandb[aws]",
            lazy=False,
        )

        from botocore.client import Config  # type: ignore

        s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL")
        config_kwargs: dict[str, Any] = {
            "user_agent_extra": f"wandb/{_wandb_version}",
        }
        if s3_endpoint and self._resolve_s3_provider(s3_endpoint):
            config_kwargs["s3"] = {"addressing_style": "virtual"}
        config = Config(**config_kwargs)
        self._s3 = boto.session.Session().resource(
            "s3",
            endpoint_url=s3_endpoint,
            region_name=os.getenv("AWS_REGION"),
            config=config,
        )
        self._botocore = util.get_module("botocore")
        return self._s3

    def _parse_uri(self, uri: str) -> tuple[str, str, str | None]:
        url = urlparse(uri)
        query = dict(parse_qsl(url.query))

        bucket = url.netloc
        key = url.path[1:]  # strip leading slash
        version = query.get("versionId")

        return bucket, key, version

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if not local:
            assert manifest_entry.ref is not None
            return manifest_entry.ref

        assert manifest_entry.ref is not None

        path, hit, cache_open = self._cache.check_etag_obj_path(
            URIStr(manifest_entry.ref),
            ETag(manifest_entry.digest),
            manifest_entry.size or 0,
        )
        if hit:
            return path

        self.init_boto()
        assert self._s3 is not None  # mypy: unwraps optionality
        bucket, key, _ = self._parse_uri(manifest_entry.ref)
        version = manifest_entry.extra.get("versionID")

        extra_args = {}
        if version:
            obj_version = self._s3.ObjectVersion(bucket, key, version)
            extra_args["VersionId"] = version
            obj = obj_version.Object()
        else:
            obj = self._s3.Object(bucket, key)

        try:
            etag = (
                obj_version.head()["ETag"][1:-1]  # escape leading and trailing
                if version
                else self._etag_from_obj(obj)
            )
        except self._botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise FileNotFoundError(
                    f"Unable to find {manifest_entry.path} at s3://{bucket}/{key}"
                ) from e
            raise

        if etag != manifest_entry.digest:
            # Try to match the etag with some other version.
            if version:
                raise ValueError(
                    f"Digest mismatch for object {manifest_entry.ref} with version {version}: expected {manifest_entry.digest} but found {etag}"
                )
            obj = None
            object_versions = self._s3.Bucket(bucket).object_versions.filter(Prefix=key)
            for object_version in object_versions:
                if manifest_entry.extra.get("etag") == self._etag_from_obj(
                    object_version
                ):
                    obj = object_version.Object()
                    extra_args["VersionId"] = object_version.version_id
                    break
            if obj is None:
                raise FileNotFoundError(
                    "Couldn't find object version for {}/{} matching etag {}".format(
                        bucket, key, manifest_entry.extra.get("etag")
                    )
                )

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
        self.init_boto()
        assert self._s3 is not None  # mypy: unwraps optionality

        # The passed in path might have query string parameters.
        # We only need to care about a subset, like version, when
        # parsing. Once we have that, we can store the rest of the
        # metadata in the artifact entry itself.
        bucket, key, version = self._parse_uri(path)
        path = URIStr(f"{self._scheme}://{bucket}/{key}")

        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        if not checksum:
            entry_path = name or (key if key != "" else bucket)
            return [ArtifactManifestEntry(path=entry_path, ref=path, digest=path)]

        # If an explicit version is specified, use that. Otherwise, use the head version.
        objs = (
            [self._s3.ObjectVersion(bucket, key, version).Object()]
            if version
            else [self._s3.Object(bucket, key)]
        )
        multi = False
        if key != "":
            try:
                objs[0].load()
                # S3 lacks true folders, but a folder key can reference a valid
                # file, which prevents recursive uploads. Check whether the
                # object's metadata marks it as a directory and perform a
                # multi-file upload if so.
                if "x-directory" in objs[0].content_type:
                    multi = True
            except self._botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    multi = True
                else:
                    raise CommError(
                        f"Unable to connect to S3 ({e.response['Error']['Code']}): "
                        f"{e.response['Error']['Message']}. Check that your "
                        "authentication credentials are valid and that your region is "
                        "set correctly."
                    )
        else:
            multi = True

        with TimedIf(multi):
            if multi:
                termlog(
                    f'Generating checksum for up to {max_objects} objects in "{bucket}/{key}"... ',
                    newline=False,
                )
                if key != "":
                    objs = (
                        self._s3.Bucket(bucket)
                        .objects.filter(Prefix=key)
                        .limit(max_objects)
                    )
                else:
                    objs = self._s3.Bucket(bucket).objects.limit(max_objects)
            # Weird iterator scoping makes us assign this to a local function
            size = self._size_from_obj
            entries = [
                self._entry_from_obj(obj, path, name, prefix=key, multi=multi)
                for obj in objs
                if size(obj) > 0
            ]

        if len(entries) > max_objects:
            raise ValueError(
                f"Exceeded {max_objects} objects tracked, pass max_objects to add_reference"
            )
        return entries

    def _size_from_obj(self, obj: boto3.s3.Object | boto3.s3.ObjectSummary) -> int:
        # ObjectSummary has size, Object has content_length
        size: int
        if hasattr(obj, "size"):
            size = obj.size
        else:
            size = obj.content_length
        return size

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
        bucket, key, _ = self._parse_uri(path)

        # Always use posix paths, since that's what S3 uses.
        posix_key = PurePosixPath(obj.key)  # the bucket key
        posix_path = PurePosixPath(bucket) / key  # the path, with the scheme stripped
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
            digest=ETag(self._etag_from_obj(obj)),
            size=self._size_from_obj(obj),
            extra=self._extra_from_obj(obj),
        )

    @staticmethod
    def _etag_from_obj(obj: boto3.s3.Object | boto3.s3.ObjectSummary) -> ETag:
        etag: ETag
        etag = obj.e_tag[1:-1]  # escape leading and trailing quote
        return etag

    def _extra_from_obj(
        self, obj: boto3.s3.Object | boto3.s3.ObjectSummary
    ) -> dict[str, str]:
        extra = {
            "etag": obj.e_tag[1:-1],  # escape leading and trailing quote
        }
        if not hasattr(obj, "version_id"):
            # Convert ObjectSummary to Object to get the version_id.
            obj = self._s3.Object(obj.bucket_name, obj.key)  # type: ignore[union-attr]
        if hasattr(obj, "version_id") and obj.version_id and obj.version_id != "null":
            extra["versionID"] = obj.version_id
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

        # URL schemes and hostnames are case-insensitive; lowercase before
        # comparing so e.g. ``HTTPS://CWOBJECT.COM`` still matches.
        url = url.lower()

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

    _B2_NETLOC_REGEX: re.Pattern[str] = re.compile(
        r"""
        # Path-style S3 endpoint: "s3.<region>.backblazeb2.com"
        s3\.[a-z0-9-]+\.backblazeb2\.com
        |
        # Virtual-hosted-style: "<bucket>.s3.<region>.backblazeb2.com"
        [a-z0-9][a-z0-9.-]*\.s3\.[a-z0-9-]+\.backblazeb2\.com
        """,
        flags=re.VERBOSE,
    )

    def _is_backblaze_endpoint(self, endpoint_url: str) -> bool:
        """Return True if ``endpoint_url`` points at a Backblaze B2 S3 endpoint.

        B2's S3-compatible API supports virtual-hosted-style addressing, which
        is what AWS now treats as the default; we set that explicitly so wandb
        artifact references work without per-bucket DNS surprises.
        """
        if not (url := endpoint_url.strip().rstrip("/")):
            return False

        # B2's S3 endpoints are HTTPS-only. Hostnames are case-insensitive, so
        # lowercase before matching.
        https_url = ensureprefix(url.lower(), "https://")
        netloc = urlparse(https_url).netloc
        return bool(self._B2_NETLOC_REGEX.fullmatch(netloc))

    # Registry of supported S3-compatible non-AWS providers. To add a new one:
    # (1) define ``_is_<provider>_endpoint`` above with its matching logic;
    # (2) add the (name, detector) entry below. Call sites that need to
    # branch on "is this any S3-compatible non-AWS endpoint?" should call
    # ``_resolve_s3_provider`` and check that the return value is not ``None``.
    _S3_COMPATIBLE_PROVIDER_DETECTORS: ClassVar[
        dict[str, Callable[[S3Handler, str], bool]]
    ] = {
        "coreweave": _is_coreweave_endpoint,
        "backblaze": _is_backblaze_endpoint,
    }

    def _resolve_s3_provider(self, endpoint_url: str) -> str | None:
        """Return the matching S3-compatible provider name (or ``None``).

        ``None`` means the URL is not a recognized S3-compatible non-AWS
        endpoint (i.e. it is either AWS S3 itself or an unrecognized host).
        """
        for name, detector in self._S3_COMPATIBLE_PROVIDER_DETECTORS.items():
            if detector(self, endpoint_url):
                return name
        return None
