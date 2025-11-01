"""HTTP storage handler."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional
from urllib.parse import ParseResult

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import requests
    from requests.structures import CaseInsensitiveDict

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


@pydantic_dataclass
class _ParsedEntryInfo:
    """Partial ArtifactManifestEntry fields parsed from HTTP response headers."""

    digest: Optional[str]  # noqa: UP045
    size: Optional[int]  # noqa: UP045

    @classmethod
    def from_headers(cls, hdrs: CaseInsensitiveDict) -> Self:
        return cls(
            digest=etag.strip('"') if (etag := hdrs.get("etag")) else None,
            size=hdrs.get("content-length"),
        )


class HTTPHandler(StorageHandler):
    _scheme: str
    _cache: ArtifactFileCache
    _session: requests.Session

    def __init__(self, session: requests.Session, scheme: str = "http") -> None:
        self._scheme = scheme
        self._cache = get_artifact_file_cache()
        self._session = session

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if (ref_url := manifest_entry.ref) is None:
            raise ValueError("Missing URL on artifact manifest entry")

        if not local:
            return ref_url

        expected_digest = manifest_entry.digest

        path, hit, cache_open = self._cache.check_etag_obj_path(
            ref_url,
            expected_digest,
            manifest_entry.size or 0,
        )
        if hit:
            return path

        response = self._session.get(
            ref_url,
            stream=True,
            cookies=_thread_local_api_settings.cookies,
            headers=_thread_local_api_settings.headers,
        )
        entry_info = _ParsedEntryInfo.from_headers(response.headers)
        actual_digest = entry_info.digest or ref_url
        if expected_digest != actual_digest:
            raise ValueError(
                f"Digest mismatch for url {ref_url!r}: expected {expected_digest!r} but found {actual_digest!r}"
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
    ) -> list[ArtifactManifestEntry]:
        name = name or os.path.basename(path)
        if not checksum:
            return [ArtifactManifestEntry(path=name, ref=path, digest=path)]

        with self._session.get(
            path,
            stream=True,
            cookies=_thread_local_api_settings.cookies,
            headers=_thread_local_api_settings.headers,
        ) as response:
            entry_info = _ParsedEntryInfo.from_headers(response.headers)

        return [
            ArtifactManifestEntry(
                path=name,
                ref=path,
                digest=entry_info.digest or path,
                size=entry_info.size,
                extra={"etag": etag} if (etag := entry_info.digest) else {},
            )
        ]
