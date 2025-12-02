"""HTTP storage handler."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Dict, Optional, cast
from urllib.parse import ParseResult

from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import Self

from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    import requests
    from requests.structures import CaseInsensitiveDict

    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


@pydantic_dataclass(frozen=True)
class _HttpEntryInfo:
    """Partial ArtifactManifestEntry fields parsed from an HTTP response."""

    ref: str  # The reference URL for the manifest entry, i.e. original URL of the request
    extra: Dict[str, Any]  # noqa: UP006
    digest: Optional[str]  # noqa: UP045
    size: Optional[int]  # noqa: UP045

    @classmethod
    def from_response(cls, rsp: requests.Response) -> Self:
        # NOTE(tonyyli): For continuity with prior behavior, note that:
        # - `extra["etag"]` includes leading/trailing quotes, if any, from the ETag
        # - `digest` strips leading/trailing quotes, if any, from the ETag
        #
        # - `digest` apparently falls back to the original reference URL (request URL)
        #   if no ETag is present. This is weird: wouldn't we hash the response body
        #   instead of using the URL? For now, at the time of writing/refactoring this,
        #   we'll maintain the prior behavior to minimize risk of breakage.
        headers: CaseInsensitiveDict = rsp.headers
        etag = headers.get("etag")
        ref_url = rsp.request.url
        return cls(
            ref=cast(str, ref_url),
            extra={"etag": etag} if etag else {},
            digest=etag.strip('"') if etag else ref_url,
            size=headers.get("content-length"),
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

    def _get_stream(self, url: str) -> requests.Response:
        """Returns a streaming response from a GET request to the given URL."""
        return self._session.get(
            url,
            stream=True,
        )

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
            url=ref_url, etag=expected_digest, size=manifest_entry.size or 0
        )
        if hit:
            return path

        with self._get_stream(ref_url) as rsp:
            entry_info = _HttpEntryInfo.from_response(rsp)
            if (digest := entry_info.digest) != expected_digest:
                raise ValueError(
                    f"Digest mismatch for url {ref_url!r}: expected {expected_digest!r} but found {digest!r}"
                )

            with cache_open(mode="wb") as file:
                for data in rsp.iter_content(chunk_size=128 * 1024):
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

        with self._get_stream(path) as rsp:
            entry_info = _HttpEntryInfo.from_response(rsp)
            return [ArtifactManifestEntry(path=name, **asdict(entry_info))]
