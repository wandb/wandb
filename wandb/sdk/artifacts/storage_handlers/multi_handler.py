"""Multi storage handler."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from wandb.sdk.artifacts.storage_handler import StorageHandler, _BaseStorageHandler
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


class MultiHandler(_BaseStorageHandler):
    def __init__(
        self,
        handlers: list[StorageHandler] | None = None,
        default_handler: StorageHandler | None = None,
    ) -> None:
        # group handlers by scheme for faster repeat lookups
        # handlers_by_scheme: dict[str, deque[StorageHandler]] = defaultdict(deque)
        # for h in handlers or []:
        #     handlers_by_scheme[h._scheme].append(h)
        # self._handlers = handlers_by_scheme

        self._handlers = handlers or []

        # Set the fallback handler
        self._default_handler = default_handler

    def _get_handler(self, url: str) -> StorageHandler:
        parsed = urlparse(url)
        # matching_handlers = (
        #     h for h in self._handlers[parsed.scheme] if h.can_handle(parsed)
        # )
        matching_handlers = (h for h in self._handlers if h.can_handle(parsed))
        if hdlr := next(matching_handlers, self._default_handler):
            return hdlr
        raise ValueError(f"No storage handler registered for url: {url!r}")

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if (ref_uri := manifest_entry.ref) is None:
            raise ValueError(
                f"Missing ref URI for manifest entry: {manifest_entry.path}"
            )
        return self._get_handler(ref_uri).load_path(manifest_entry, local=local)

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: str | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        return self._get_handler(path).store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )
