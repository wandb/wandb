"""HTTP storage handler."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Sequence
from urllib.parse import ParseResult

from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib.hashutil import ETag
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import requests
    from requests.structures import CaseInsensitiveDict

    from wandb.sdk.artifacts.artifact import Artifact


class HTTPHandler(StorageHandler):
    def __init__(self, session: requests.Session, scheme: str | None = None) -> None:
        self._scheme = scheme or "http"
        self._cache = get_artifact_file_cache()
        self._session = session

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

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
            ETag(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
        )
        if hit:
            return path

        response = self._session.get(
            manifest_entry.ref,
            stream=True,
            cookies=_thread_local_api_settings.cookies,
            headers=_thread_local_api_settings.headers,
        )
        response.raise_for_status()

        digest: ETag | FilePathStr | URIStr | None
        digest, size, extra = self._entry_from_headers(response.headers)
        digest = digest or manifest_entry.ref
        if manifest_entry.digest != digest:
            raise ValueError(
                f"Digest mismatch for url {manifest_entry.ref}: expected {manifest_entry.digest} but found {digest}"
            )

        with cache_open(mode="wb") as file:
            for data in response.iter_content(chunk_size=16 * 1024):
                file.write(data)
        return path

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> Sequence[ArtifactManifestEntry]:
        name = name or os.path.basename(path)
        if not checksum:
            return [ArtifactManifestEntry(path=name, ref=path, digest=path)]

        with self._session.get(
            path,
            stream=True,
            cookies=_thread_local_api_settings.cookies,
            headers=_thread_local_api_settings.headers,
        ) as response:
            response.raise_for_status()
            digest: ETag | FilePathStr | URIStr | None
            digest, size, extra = self._entry_from_headers(response.headers)
            digest = digest or path
        return [
            ArtifactManifestEntry(
                path=name, ref=path, digest=digest, size=size, extra=extra
            )
        ]

    def _entry_from_headers(
        self, headers: CaseInsensitiveDict
    ) -> tuple[ETag | None, int | None, dict[str, str]]:
        response_headers = {k.lower(): v for k, v in headers.items()}
        size = None
        if response_headers.get("content-length", None):
            size = int(response_headers["content-length"])

        digest = response_headers.get("etag", None)
        extra = {}
        if digest:
            extra["etag"] = digest
        if digest and digest[:1] == '"' and digest[-1:] == '"':
            digest = digest[1:-1]  # trim leading and trailing quotes around etag
        return digest, size, extra
