"""S3 storage handler."""

import os
import time
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qsl, urlparse

from wandb import util
from wandb.errors import CommError
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

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


class S3Handler(StorageHandler):
    _s3: Optional["boto3.resources.base.ServiceResource"]
    _scheme: str

    def __init__(self, scheme: Optional[str] = None) -> None:
        self._scheme = scheme or "s3"
        self._s3 = None
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: "ParseResult") -> bool:
        return parsed_url.scheme == self._scheme

    def init_boto(self) -> "boto3.resources.base.ServiceResource":
        if self._s3 is not None:
            return self._s3
        boto: boto3 = util.get_module(
            "boto3",
            required="s3:// references requires the boto3 library, run pip install wandb[aws]",
            lazy=False,
        )
        self._s3 = boto.session.Session().resource(
            "s3",
            endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION"),
        )
        self._botocore = util.get_module("botocore")
        return self._s3

    def _parse_uri(self, uri: str) -> Tuple[str, str, Optional[str]]:
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
    ) -> Union[URIStr, FilePathStr]:
        if not local:
            assert manifest_entry.ref is not None
            return manifest_entry.ref

        assert manifest_entry.ref is not None

        path, hit, cache_open = self._cache.check_etag_obj_path(
            URIStr(manifest_entry.ref),
            ETag(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
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
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
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
        start_time = None
        multi = False
        if key != "":
            try:
                objs[0].load()
                # S3 doesn't have real folders, however there are cases where the folder key has a valid file which will not
                # trigger a recursive upload.
                # we should check the object's metadata says it is a directory and do a multi file upload if it is
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

        if multi:
            start_time = time.time()
            termlog(
                'Generating checksum for up to %i objects in "%s/%s"... '
                % (max_objects, bucket, key),
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
        if start_time is not None:
            termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        if len(entries) > max_objects:
            raise ValueError(
                "Exceeded %i objects tracked, pass max_objects to add_reference"
                % max_objects
            )
        return entries

    def _size_from_obj(
        self, obj: Union["boto3.s3.Object", "boto3.s3.ObjectSummary"]
    ) -> int:
        # ObjectSummary has size, Object has content_length
        size: int
        if hasattr(obj, "size"):
            size = obj.size
        else:
            size = obj.content_length
        return size

    def _entry_from_obj(
        self,
        obj: Union["boto3.s3.Object", "boto3.s3.ObjectSummary"],
        path: str,
        name: Optional[StrPath] = None,
        prefix: str = "",
        multi: bool = False,
    ) -> ArtifactManifestEntry:
        """Create an ArtifactManifestEntry from an S3 object.

        Arguments:
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
    def _etag_from_obj(obj: Union["boto3.s3.Object", "boto3.s3.ObjectSummary"]) -> ETag:
        etag: ETag
        etag = obj.e_tag[1:-1]  # escape leading and trailing quote
        return etag

    def _extra_from_obj(
        self, obj: Union["boto3.s3.Object", "boto3.s3.ObjectSummary"]
    ) -> Dict[str, str]:
        extra = {
            "etag": obj.e_tag[1:-1],  # escape leading and trailing quote
        }
        if not hasattr(obj, "version_id"):
            # Convert ObjectSummary to Object to get the version_id.
            obj = self._s3.Object(obj.bucket_name, obj.key)  # type: ignore[union-attr]
        if hasattr(obj, "version_id") and obj.version_id and obj.version_id != "null":
            extra["versionID"] = obj.version_id
        return extra
