"""WandB storage policy."""

import hashlib
import math
import os
import shutil
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union
from urllib.parse import quote

import requests
import urllib3

from wandb.errors.term import termwarn
from wandb.sdk.artifacts.artifact_file_cache import (
    ArtifactFileCache,
    get_artifact_file_cache,
)
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.artifacts.storage_handlers.azure_handler import AzureHandler
from wandb.sdk.artifacts.storage_handlers.gcs_handler import GCSHandler
from wandb.sdk.artifacts.storage_handlers.http_handler import HTTPHandler
from wandb.sdk.artifacts.storage_handlers.local_file_handler import LocalFileHandler
from wandb.sdk.artifacts.storage_handlers.multi_handler import MultiHandler
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler
from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
from wandb.sdk.artifacts.storage_handlers.wb_artifact_handler import WBArtifactHandler
from wandb.sdk.artifacts.storage_handlers.wb_local_artifact_handler import (
    WBLocalArtifactHandler,
)
from wandb.sdk.artifacts.storage_layout import StorageLayout
from wandb.sdk.artifacts.storage_policies.register import WANDB_STORAGE_POLICY
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib.hashutil import B64MD5, b64_to_hex_id, hex_to_b64_id
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.internal import progress

# Sleep length: 0, 2, 4, 8, 16, 32, 64, 120, 120, 120, 120, 120, 120, 120, 120, 120
# seconds, i.e. a total of 20min 6s.
_REQUEST_RETRY_STRATEGY = urllib3.util.retry.Retry(
    backoff_factor=1,
    total=16,
    status_forcelist=(308, 408, 409, 429, 500, 502, 503, 504),
)
_REQUEST_POOL_CONNECTIONS = 64
_REQUEST_POOL_MAXSIZE = 64

# AWS S3 max upload parts without having to make additional requests for extra parts
S3_MAX_PART_NUMBERS = 1000
S3_MIN_MULTI_UPLOAD_SIZE = 2 * 1024**3
S3_MAX_MULTI_UPLOAD_SIZE = 5 * 1024**4


class WandbStoragePolicy(StoragePolicy):
    @classmethod
    def name(cls) -> str:
        return WANDB_STORAGE_POLICY

    @classmethod
    def from_config(
        cls, config: Dict, api: Optional[InternalApi] = None
    ) -> "WandbStoragePolicy":
        return cls(config=config, api=api)

    def __init__(
        self,
        config: Optional[Dict] = None,
        cache: Optional[ArtifactFileCache] = None,
        api: Optional[InternalApi] = None,
    ) -> None:
        self._cache = cache or get_artifact_file_cache()
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
        azure = AzureHandler()
        http = HTTPHandler(self._session)
        https = HTTPHandler(self._session, scheme="https")
        artifact = WBArtifactHandler()
        local_artifact = WBLocalArtifactHandler()
        file_handler = LocalFileHandler()

        self._api = api or InternalApi()
        self._handler = MultiHandler(
            handlers=[
                s3,
                gcs,
                azure,
                http,
                https,
                artifact,
                local_artifact,
                file_handler,
            ],
            default_handler=TrackingHandler(),
        )

    def config(self) -> Dict:
        return self._config

    def load_file(
        self,
        artifact: "Artifact",
        manifest_entry: "ArtifactManifestEntry",
        dest_path: Optional[str] = None,
    ) -> FilePathStr:
        if dest_path is not None:
            self._cache._override_cache_path = dest_path

        path, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
        )
        if hit:
            return path

        if manifest_entry._download_url is not None:
            response = self._session.get(manifest_entry._download_url, stream=True)
            try:
                response.raise_for_status()
            except Exception:
                # Signed URL might have expired, fall back to fetching it one by one.
                manifest_entry._download_url = None
        if manifest_entry._download_url is None:
            auth = None
            http_headers = _thread_local_api_settings.headers or {}
            if self._api.access_token is not None:
                http_headers["Authorization"] = f"Bearer {self._api.access_token}"
            elif _thread_local_api_settings.cookies is None:
                auth = ("api", self._api.api_key or "")

            response = self._session.get(
                self._file_url(self._api, artifact.entity, manifest_entry),
                auth=auth,
                cookies=_thread_local_api_settings.cookies,
                headers=http_headers,
                stream=True,
            )
            response.raise_for_status()

        with cache_open(mode="wb") as file:
            for data in response.iter_content(chunk_size=16 * 1024):
                file.write(data)
        return path

    def store_reference(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        return self._handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )

    def load_reference(
        self,
        manifest_entry: "ArtifactManifestEntry",
        local: bool = False,
        dest_path: Optional[str] = None,
    ) -> Union[FilePathStr, URIStr]:
        assert manifest_entry.ref is not None
        used_handler = self._handler._get_handler(manifest_entry.ref)
        if hasattr(used_handler, "_cache") and (dest_path is not None):
            used_handler._cache._override_cache_path = dest_path
        return self._handler.load_path(manifest_entry, local)

    def _file_url(
        self,
        api: InternalApi,
        entity_name: str,
        manifest_entry: "ArtifactManifestEntry",
    ) -> str:
        storage_layout = self._config.get("storageLayout", StorageLayout.V1)
        storage_region = self._config.get("storageRegion", "default")
        md5_hex = b64_to_hex_id(B64MD5(manifest_entry.digest))

        if storage_layout == StorageLayout.V1:
            return "{}/artifacts/{}/{}".format(
                api.settings("base_url"), entity_name, md5_hex
            )
        elif storage_layout == StorageLayout.V2:
            return "{}/artifactsV2/{}/{}/{}/{}".format(
                api.settings("base_url"),
                storage_region,
                entity_name,
                quote(
                    manifest_entry.birth_artifact_id
                    if manifest_entry.birth_artifact_id is not None
                    else ""
                ),
                md5_hex,
            )
        else:
            raise Exception(f"unrecognized storage layout: {storage_layout}")

    def s3_multipart_file_upload(
        self,
        file_path: str,
        chunk_size: int,
        hex_digests: Dict[int, str],
        multipart_urls: Dict[int, str],
        extra_headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        etags = []
        part_number = 1

        with open(file_path, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                md5_b64_str = str(hex_to_b64_id(hex_digests[part_number]))
                upload_resp = self._api.upload_multipart_file_chunk_retry(
                    multipart_urls[part_number],
                    data,
                    extra_headers={
                        "content-md5": md5_b64_str,
                        "content-length": str(len(data)),
                        "content-type": extra_headers.get("Content-Type", ""),
                    },
                )
                assert upload_resp is not None
                etags.append(
                    {"partNumber": part_number, "hexMD5": upload_resp.headers["ETag"]}
                )
                part_number += 1
        return etags

    def default_file_upload(
        self,
        upload_url: str,
        file_path: str,
        extra_headers: Dict[str, Any],
        progress_callback: Optional["progress.ProgressFn"] = None,
    ) -> None:
        """Upload a file to the artifact store and write to cache."""
        with open(file_path, "rb") as file:
            # This fails if we don't send the first byte before the signed URL expires.
            self._api.upload_file_retry(
                upload_url,
                file,
                progress_callback,
                extra_headers=extra_headers,
            )

    def calc_chunk_size(self, file_size: int) -> int:
        # Default to chunk size of 100MiB. S3 has cap of 10,000 upload parts.
        # If file size exceeds the default chunk size, recalculate chunk size.
        default_chunk_size = 100 * 1024**2
        if default_chunk_size * S3_MAX_PART_NUMBERS < file_size:
            return math.ceil(file_size / S3_MAX_PART_NUMBERS)
        return default_chunk_size

    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: "ArtifactManifestEntry",
        preparer: "StepPrepare",
        progress_callback: Optional["progress.ProgressFn"] = None,
    ) -> bool:
        """Upload a file to the artifact store.

        Returns:
            True if the file was a duplicate (did not need to be uploaded),
            False if it needed to be uploaded or was a reference (nothing to dedupe).
        """
        file_size = entry.size if entry.size is not None else 0
        chunk_size = self.calc_chunk_size(file_size)
        upload_parts = []
        hex_digests = {}
        file_path = entry.local_path if entry.local_path is not None else ""
        # Logic for AWS s3 multipart upload.
        # Only chunk files if larger than 2 GiB. Currently can only support up to 5TiB.
        if (
            file_size >= S3_MIN_MULTI_UPLOAD_SIZE
            and file_size <= S3_MAX_MULTI_UPLOAD_SIZE
        ):
            part_number = 1
            with open(file_path, "rb") as f:
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    hex_digest = hashlib.md5(data).hexdigest()
                    upload_parts.append(
                        {"hexMD5": hex_digest, "partNumber": part_number}
                    )
                    hex_digests[part_number] = hex_digest
                    part_number += 1

        resp = preparer.prepare(
            {
                "artifactID": artifact_id,
                "artifactManifestID": artifact_manifest_id,
                "name": entry.path,
                "md5": entry.digest,
                "uploadPartsInput": upload_parts,
            }
        ).get()

        entry.birth_artifact_id = resp.birth_artifact_id

        multipart_urls = resp.multipart_upload_urls
        if resp.upload_url is None:
            return True
        if entry.local_path is None:
            return False
        extra_headers = {
            header.split(":", 1)[0]: header.split(":", 1)[1]
            for header in (resp.upload_headers or {})
        }

        # This multipart upload isn't available, do a regular single url upload
        if multipart_urls is None and resp.upload_url:
            self.default_file_upload(
                resp.upload_url, file_path, extra_headers, progress_callback
            )
        else:
            if multipart_urls is None:
                raise ValueError(f"No multipart urls to upload for file: {file_path}")
            # Upload files using s3 multipart upload urls
            etags = self.s3_multipart_file_upload(
                file_path,
                chunk_size,
                hex_digests,
                multipart_urls,
                extra_headers,
            )
            assert resp.storage_path is not None
            self._api.complete_multipart_upload_artifact(
                artifact_id, resp.storage_path, etags, resp.upload_id
            )
        self._write_cache(entry)

        return False

    def _write_cache(self, entry: "ArtifactManifestEntry") -> None:
        if entry.local_path is None:
            return

        # Cache upon successful upload.
        _, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(entry.digest),
            entry.size if entry.size is not None else 0,
        )

        staging_dir = get_staging_dir()
        try:
            if not entry.skip_cache and not hit:
                with cache_open("wb") as f, open(entry.local_path, "rb") as src:
                    shutil.copyfileobj(src, f)
            if entry.local_path.startswith(staging_dir):
                # Delete staged files here instead of waiting till
                # all the files are uploaded
                os.chmod(entry.local_path, 0o600)
                os.remove(entry.local_path)
        except OSError as e:
            termwarn(f"Failed to cache {entry.local_path}, ignoring {e}")
