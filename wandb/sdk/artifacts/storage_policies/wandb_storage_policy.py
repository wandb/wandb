"""WandB storage policy."""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import shutil
from collections import deque
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Sequence
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wandb.errors.term import termwarn
from wandb.proto.wandb_internal_pb2 import ServerFeature
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
from wandb.sdk.artifacts.storage_policies._multipart import (
    S3_MAX_MULTI_UPLOAD_SIZE,
    S3_MIN_MULTI_UPLOAD_SIZE,
    KiB,
    calc_chunk_size,
    multipart_file_download,
    scan_chunks,
)
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
    from wandb.sdk.internal.internal_api import CreateArtifactFileSpecInput

# Sleep length: 0, 2, 4, 8, 16, 32, 64, 120, 120, 120, 120, 120, 120, 120, 120, 120
# seconds, i.e. a total of 20min 6s.
_REQUEST_RETRY_STRATEGY = Retry(
    backoff_factor=1,
    total=16,
    status_forcelist=(308, 408, 409, 429, 500, 502, 503, 504),
)
_REQUEST_POOL_CONNECTIONS = 64
_REQUEST_POOL_MAXSIZE = 64


logger = logging.getLogger(__name__)


def _raise_for_status(response: requests.Response, *_, **__) -> None:
    """A `requests.Session` hook to raise for status on all requests."""
    response.raise_for_status()


def _make_http_session() -> requests.Session:
    """A factory for a `requests.Session` for use in artifact storage handlers."""
    session = requests.Session()

    # Explicitly configure the retry strategy for http/https adapters.
    adapter = HTTPAdapter(
        max_retries=_REQUEST_RETRY_STRATEGY,
        pool_connections=_REQUEST_POOL_CONNECTIONS,
        pool_maxsize=_REQUEST_POOL_MAXSIZE,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Always raise on HTTP status errors.
    session.hooks["response"].append(_raise_for_status)
    return session


def _make_multi_handler(session: requests.Session) -> MultiHandler:
    return MultiHandler(
        handlers=[
            S3Handler(),  # s3
            GCSHandler(),  # gcs
            AzureHandler(),  # azure
            HTTPHandler(session, scheme="http"),  # http
            HTTPHandler(session, scheme="https"),  # https
            WBArtifactHandler(),  # artifact
            WBLocalArtifactHandler(),  # local_artifact
            LocalFileHandler(),  # file_handler
        ],
        default_handler=TrackingHandler(),
    )


class WandbStoragePolicy(StoragePolicy):
    @classmethod
    def name(cls) -> str:
        return WANDB_STORAGE_POLICY

    @classmethod
    def from_config(
        cls, config: dict[str, Any], api: InternalApi | None = None
    ) -> WandbStoragePolicy:
        return cls(config=config, api=api)

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        cache: ArtifactFileCache | None = None,
        api: InternalApi | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config or {}
        self._cache = cache or get_artifact_file_cache()
        self._session = session or _make_http_session()
        self._api = api or InternalApi()
        self._handler = _make_multi_handler(self._session)

    def config(self) -> dict[str, Any]:
        return self._config

    def load_file(
        self,
        artifact: Artifact,
        manifest_entry: ArtifactManifestEntry,
        dest_path: str | None = None,
        # FIXME: We should avoid passing the executor into multiple inner functions,
        # it leads to confusing code and opaque tracebacks/call stacks.
        executor: concurrent.futures.Executor | None = None,
    ) -> FilePathStr:
        """Use cache or download the file using signed url.

        Args:
            executor: Passed from caller, artifact has a thread pool for multi file download.
                Reuse the thread pool for multi part download. The thread pool is closed when
                artifact download is done.

                If this is None, download the file serially.
        """
        if dest_path is not None:
            self._cache._override_cache_path = dest_path

        path, hit, cache_open = self._cache.check_md5_obj_path(
            manifest_entry.digest,
            manifest_entry.size or 0,
        )
        if hit:
            return path

        if download_url := manifest_entry._download_url:
            # Use multipart parallel download for large file
            if executor and manifest_entry.size:
                multipart_file_download(
                    executor,
                    self._session,
                    download_url,
                    manifest_entry.size,
                    cache_open,
                )
                return path
            # Serial download
            try:
                response = self._session.get(download_url, stream=True)
            except requests.HTTPError:
                # Signed URL might have expired, fall back to fetching it one by one.
                download_url = None

        if download_url is None:
            auth = None
            headers = _thread_local_api_settings.headers
            cookies = _thread_local_api_settings.cookies

            # For auth, prefer using (in order): auth header, cookies, HTTP Basic Auth
            if token := self._api.access_token:
                headers = {**(headers or {}), "Authorization": f"Bearer {token}"}
            elif cookies is not None:
                auth = ("api", self._api.api_key or "")

            file_url = self._file_url(
                self._api,
                artifact.entity,
                artifact.project,
                artifact.name.split(":")[0],
                manifest_entry,
            )
            response = self._session.get(
                file_url, auth=auth, cookies=cookies, headers=headers, stream=True
            )

        with cache_open(mode="wb") as file:
            for data in response.iter_content(chunk_size=16 * KiB):
                file.write(data)
        return path

    def store_reference(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        return self._handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )

    def load_reference(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
        dest_path: str | None = None,
    ) -> FilePathStr | URIStr:
        assert manifest_entry.ref is not None
        used_handler = self._handler._get_handler(manifest_entry.ref)
        if hasattr(used_handler, "_cache") and (dest_path is not None):
            used_handler._cache._override_cache_path = dest_path
        return self._handler.load_path(manifest_entry, local)

    def _file_url(
        self,
        api: InternalApi,
        entity_name: str,
        project_name: str,
        artifact_name: str,
        entry: ArtifactManifestEntry,
    ) -> str:
        layout = self._config.get("storageLayout", StorageLayout.V1)
        region = self._config.get("storageRegion", "default")
        md5_hex = b64_to_hex_id(entry.digest)

        base_url: str = api.settings("base_url")

        if layout == StorageLayout.V1:
            return f"{base_url}/artifacts/{entity_name}/{md5_hex}"

        if layout == StorageLayout.V2:
            birth_artifact_id = entry.birth_artifact_id or ""
            if api._server_supports(
                ServerFeature.ARTIFACT_COLLECTION_MEMBERSHIP_FILE_DOWNLOAD_HANDLER
            ):
                return f"{base_url}/artifactsV2/{region}/{quote(entity_name)}/{quote(project_name)}/{quote(artifact_name)}/{quote(birth_artifact_id)}/{md5_hex}/{entry.path.name}"

            return f"{base_url}/artifactsV2/{region}/{entity_name}/{quote(birth_artifact_id)}/{md5_hex}"

        raise ValueError(f"unrecognized storage layout: {layout!r}")

    def s3_multipart_file_upload(
        self,
        file_path: str,
        chunk_size: int,
        hex_digests: dict[int, str],
        multipart_urls: dict[int, str],
        extra_headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        etags: deque[dict[str, Any]] = deque()
        file_chunks = scan_chunks(file_path, chunk_size)
        for num, data in enumerate(file_chunks, start=1):
            rsp = self._api.upload_multipart_file_chunk_retry(
                multipart_urls[num],
                data,
                extra_headers={
                    "content-md5": hex_to_b64_id(hex_digests[num]),
                    "content-length": str(len(data)),
                    "content-type": extra_headers.get("Content-Type") or "",
                },
            )
            assert rsp is not None
            etags.append({"partNumber": num, "hexMD5": rsp.headers["ETag"]})
        return list(etags)

    def default_file_upload(
        self,
        upload_url: str,
        file_path: str,
        extra_headers: dict[str, Any],
        progress_callback: progress.ProgressFn | None = None,
    ) -> None:
        """Upload a file to the artifact store and write to cache."""
        with open(file_path, "rb") as file:
            # This fails if we don't send the first byte before the signed URL expires.
            self._api.upload_file_retry(
                upload_url, file, progress_callback, extra_headers=extra_headers
            )

    def store_file(
        self,
        artifact_id: str,
        artifact_manifest_id: str,
        entry: ArtifactManifestEntry,
        preparer: StepPrepare,
        progress_callback: progress.ProgressFn | None = None,
    ) -> bool:
        """Upload a file to the artifact store.

        Returns:
            True if the file was a duplicate (did not need to be uploaded),
            False if it needed to be uploaded or was a reference (nothing to dedupe).
        """
        file_size = entry.size or 0
        chunk_size = calc_chunk_size(file_size)
        file_path = entry.local_path or ""
        # Logic for AWS s3 multipart upload.
        # Only chunk files if larger than 2 GiB. Currently can only support up to 5TiB.
        if S3_MIN_MULTI_UPLOAD_SIZE <= file_size <= S3_MAX_MULTI_UPLOAD_SIZE:
            file_chunks = scan_chunks(file_path, chunk_size)
            upload_parts = [
                {"partNumber": num, "hexMD5": hashlib.md5(data).hexdigest()}
                for num, data in enumerate(file_chunks, start=1)
            ]
            hex_digests = dict(map(itemgetter("partNumber", "hexMD5"), upload_parts))
        else:
            upload_parts = []
            hex_digests = {}

        file_spec: CreateArtifactFileSpecInput = {
            "artifactID": artifact_id,
            "artifactManifestID": artifact_manifest_id,
            "name": entry.path,
            "md5": entry.digest,
            "uploadPartsInput": upload_parts,
        }
        resp = preparer.prepare(file_spec).get()

        entry.birth_artifact_id = resp.birth_artifact_id

        if resp.upload_url is None:
            return True
        if entry.local_path is None:
            return False

        extra_headers = dict(hdr.split(":", 1) for hdr in (resp.upload_headers or []))

        # This multipart upload isn't available, do a regular single url upload
        if (multipart_urls := resp.multipart_upload_urls) is None and resp.upload_url:
            self.default_file_upload(
                resp.upload_url, file_path, extra_headers, progress_callback
            )
        elif multipart_urls is None:
            raise ValueError(f"No multipart urls to upload for file: {file_path}")
        else:
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

    def _write_cache(self, entry: ArtifactManifestEntry) -> None:
        if entry.local_path is None:
            return

        # Cache upon successful upload.
        _, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(entry.digest),
            entry.size if entry.size is not None else 0,
        )

        staging_dir = get_staging_dir()
        try:
            if not (entry.skip_cache or hit):
                with cache_open("wb") as f, open(entry.local_path, "rb") as src:
                    shutil.copyfileobj(src, f)
            if entry.local_path.startswith(staging_dir):
                # Delete staged files here instead of waiting till
                # all the files are uploaded
                os.chmod(entry.local_path, 0o600)
                os.remove(entry.local_path)
        except OSError as e:
            termwarn(f"Failed to cache {entry.local_path}, ignoring {e}")
