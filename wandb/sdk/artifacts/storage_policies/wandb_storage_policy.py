"""WandB storage policy."""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import shutil
from collections import deque
from operator import itemgetter
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests
from typing_extensions import assert_never

from wandb.errors.term import termwarn
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._gqlutils import server_supports
from wandb.sdk.artifacts._models.storage import StoragePolicyConfig
from wandb.sdk.artifacts.artifact_file_cache import (
    ArtifactFileCache,
    get_artifact_file_cache,
)
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.artifacts.storage_handlers.multi_handler import MultiHandler
from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
from wandb.sdk.artifacts.storage_layout import StorageLayout
from wandb.sdk.artifacts.storage_policies._multipart import (
    MAX_MULTI_UPLOAD_SIZE,
    MIN_MULTI_UPLOAD_SIZE,
    KiB,
    calc_part_size,
    multipart_download,
    scan_chunks,
)
from wandb.sdk.artifacts.storage_policies.register import WANDB_STORAGE_POLICY
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib.hashutil import b64_to_hex_id, hex_to_b64_id
from wandb.sdk.lib.paths import FilePathStr, URIStr

from ._factories import make_http_session, make_storage_handlers
from ._url_provider import SharedUrlProvider

if TYPE_CHECKING:
    import requests

    from wandb.filesync.step_prepare import StepPrepare
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
    from wandb.sdk.internal import progress

logger = logging.getLogger(__name__)


class WandbStoragePolicy(StoragePolicy):
    @classmethod
    def name(cls) -> str:
        return WANDB_STORAGE_POLICY

    @classmethod
    def from_config(cls, config: StoragePolicyConfig) -> WandbStoragePolicy:
        return cls(config=config)

    def __init__(
        self,
        config: StoragePolicyConfig | None = None,
        cache: ArtifactFileCache | None = None,
        api: InternalApi | None = None,
    ) -> None:
        self._config = StoragePolicyConfig.model_validate(config or {})

        # Don't instantiate these right away if missing, instead defer to the
        # first time they're needed. Otherwise, at the time of writing, this
        # significantly slows down `Artifact.__init__()`.
        self._maybe_cache = cache
        self._maybe_api = api
        self._maybe_session: requests.Session | None = None
        self._maybe_handler: MultiHandler | None = None

    @property
    def _cache(self) -> ArtifactFileCache:
        if self._maybe_cache is None:
            self._maybe_cache = get_artifact_file_cache()
        return self._maybe_cache

    @property
    def _api(self) -> InternalApi:
        if self._maybe_api is None:
            self._maybe_api = InternalApi()
        return self._maybe_api

    @_api.setter
    def _api(self, api: InternalApi) -> None:
        self._maybe_api = api

    @property
    def _session(self) -> requests.Session:
        if self._maybe_session is None:
            self._maybe_session = make_http_session()
        return self._maybe_session

    @property
    def _handler(self) -> MultiHandler:
        if self._maybe_handler is None:
            self._maybe_handler = MultiHandler(
                handlers=make_storage_handlers(self._session),
                default_handler=TrackingHandler(),
            )
        return self._maybe_handler

    def config(self) -> dict[str, Any]:
        return self._config.model_dump(exclude_none=True)

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
            executor: A thread pool provided by the caller for multi-file
                downloads. Reuse the thread pool for multipart downloads; it is
                closed when the artifact download completes. If this is `None`,
                download the file serially.
        """
        if dest_path is not None:
            self._cache._override_cache_path = dest_path

        path, hit, cache_open = self._cache.check_md5_obj_path(
            manifest_entry.digest,
            size=manifest_entry.size or 0,
        )
        if hit:
            return path

        if url := manifest_entry._download_url:
            # Use multipart parallel download for large file
            if executor and (size := manifest_entry.size):
                # Create URL provider with GraphQL-based refresh callback
                def fetch_fresh_url() -> str:
                    from wandb.apis.public.artifacts import ArtifactFiles

                    if artifact._client is None:
                        raise RuntimeError("Client not initialized")

                    files = ArtifactFiles(
                        artifact._client,
                        artifact,
                        names=[str(manifest_entry.path)],
                        per_page=1,
                    )

                    try:
                        file = next(iter(files))
                    except StopIteration:
                        raise ValueError(
                            f"Failed to fetch URL for file: {manifest_entry.path}"
                        )
                    else:
                        return file.direct_url

                url_provider = SharedUrlProvider(
                    initial_url=url,
                    fetch_fn=fetch_fresh_url,
                )

                multipart_download(
                    executor,
                    self._session,
                    size,
                    cache_open,
                    url_provider=url_provider,
                )
                return path

            # Serial download
            try:
                response = self._session.get(url, stream=True)
            except requests.HTTPError:
                # Signed URL might have expired, fall back to fetching it one by one.
                manifest_entry._download_url = None

        if manifest_entry._download_url is None:
            auth = None
            headers: dict[str, str] = {}

            # For auth, prefer using (in order): auth header, cookies, HTTP Basic Auth
            if token := self._api.access_token:
                headers = {"Authorization": f"Bearer {token}"}
            else:
                auth = ("api", self._api.api_key or "")

            file_url = self._file_url(artifact, manifest_entry)
            response = self._session.get(
                file_url,
                auth=auth,
                headers=headers,
                stream=True,
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
    ) -> list[ArtifactManifestEntry]:
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

    def _file_url(self, artifact: Artifact, entry: ArtifactManifestEntry) -> str:
        api = self._api
        base_url: str = api.settings("base_url")

        layout = self._config.storage_layout or StorageLayout.V1
        region = self._config.storage_region or "default"

        entity = artifact.entity
        project = artifact.project
        collection = artifact.name.split(":")[0]

        hexhash = b64_to_hex_id(entry.digest)

        if layout is StorageLayout.V1:
            return f"{base_url}/artifacts/{entity}/{hexhash}"

        if layout is StorageLayout.V2:
            birth_artifact_id = entry.birth_artifact_id or ""
            if server_supports(
                api.client, pb.ARTIFACT_COLLECTION_MEMBERSHIP_FILE_DOWNLOAD_HANDLER
            ):
                return f"{base_url}/artifactsV2/{region}/{quote(entity)}/{quote(project)}/{quote(collection)}/{quote(birth_artifact_id)}/{hexhash}/{entry.path.name}"

            return f"{base_url}/artifactsV2/{region}/{quote(entity)}/{quote(birth_artifact_id)}/{hexhash}"

        assert_never(layout)

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
        chunk_size = calc_part_size(file_size)
        file_path = entry.local_path or ""
        # Logic for AWS s3 multipart upload.
        # Only chunk files if larger than 2 GiB. Currently can only support up to 5TiB.
        if MIN_MULTI_UPLOAD_SIZE <= file_size <= MAX_MULTI_UPLOAD_SIZE:
            file_chunks = scan_chunks(file_path, chunk_size)
            upload_parts = [
                {"partNumber": num, "hexMD5": hashlib.md5(data).hexdigest()}
                for num, data in enumerate(file_chunks, start=1)
            ]
            hex_digests = dict(map(itemgetter("partNumber", "hexMD5"), upload_parts))
        else:
            upload_parts = []
            hex_digests = {}

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
            entry.digest,
            size=entry.size or 0,
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
