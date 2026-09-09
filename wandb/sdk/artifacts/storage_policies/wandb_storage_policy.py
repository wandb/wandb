"""WandB storage policy."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests
from typing_extensions import assert_never

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._models.storage import StoragePolicyConfig
from wandb.sdk.artifacts.artifact_file_cache import (
    ArtifactFileCache,
    get_artifact_file_cache,
)
from wandb.sdk.artifacts.storage_handlers.multi_handler import MultiHandler
from wandb.sdk.artifacts.storage_handlers.tracking_handler import TrackingHandler
from wandb.sdk.artifacts.storage_layout import StorageLayout
from wandb.sdk.artifacts.storage_policies._multipart import KiB, multipart_download
from wandb.sdk.artifacts.storage_policies.register import WANDB_STORAGE_POLICY
from wandb.sdk.artifacts.storage_policy import StoragePolicy
from wandb.sdk.lib.hashutil import b64_to_hex_id
from wandb.sdk.lib.paths import FilePathStr, URIStr

from ._factories import make_http_session, make_storage_handlers

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry

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
    ) -> None:
        self._config = StoragePolicyConfig.model_validate(config or {})

        # Don't instantiate these right away if missing, instead defer to the
        # first time they're needed. Otherwise, at the time of writing, this
        # significantly slows down `Artifact.__init__()`.
        self._maybe_cache = cache
        self._maybe_session: requests.Session | None = None
        self._maybe_handler: MultiHandler | None = None

    @property
    def _cache(self) -> ArtifactFileCache:
        if self._maybe_cache is None:
            self._maybe_cache = get_artifact_file_cache()
        return self._maybe_cache

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
            executor: A dedicated thread pool for multipart downloads,
                separate from the file-level executor. If this is `None`,
                download the file serially.
        """
        from requests import HTTPError

        if dest_path is not None:
            self._cache._override_cache_path = dest_path

        path, hit, cache_open = self._cache.check_digest_obj_path(
            manifest_entry.digest,
            size=manifest_entry.size or 0,
            algorithm=manifest_entry.digest_algorithm(),
        )
        if hit:
            return path

        if url := manifest_entry._download_url:
            # Use multipart parallel download for large file
            if executor and (size := manifest_entry.size):
                # Create URL provider with GraphQL-based refresh callback
                def fetch_fresh_url() -> str:
                    files = artifact.files(
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

                multipart_download(
                    executor,
                    self._session,
                    size,
                    cache_open,
                    initial_url=url,
                    fetch_fn=fetch_fresh_url,
                )
                return path

            # Serial download
            try:
                response = self._session.get(url, stream=True)
            except HTTPError:
                # Signed URL might have expired, fall back to fetching it one by one.
                manifest_entry._download_url = None

        if manifest_entry._download_url is None:
            auth = None
            headers: dict[str, str] = {}
            service_api = artifact._get_service_api()

            # For auth, prefer using (in order): auth header, cookies, HTTP Basic Auth
            if token := service_api.access_token():
                headers = {"Authorization": f"Bearer {token}"}
            else:
                auth = ("api", service_api.api_key or "")

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
        service_api = artifact._get_service_api()
        base_url = service_api.base_url

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
            if service_api.feature_enabled(
                pb.ARTIFACT_V2_DOWNLOAD_HANDLER_SUPPORTS_ARTIFACT_ID
            ):
                artifact_id = artifact.id or ""
                return f"{base_url}/artifactsV2/{region}/{quote(entity)}/{quote(project)}/{quote(collection)}/{quote(artifact_id)}/{quote(birth_artifact_id)}/{hexhash}/{entry.path.name}"

            return f"{base_url}/artifactsV2/{region}/{quote(entity)}/{quote(project)}/{quote(collection)}/{quote(birth_artifact_id)}/{hexhash}/{entry.path.name}"

        assert_never(layout)
