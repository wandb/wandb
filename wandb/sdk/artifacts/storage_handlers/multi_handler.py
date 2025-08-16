"""Multi storage handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence
from urllib.parse import urlparse

from wandb.sdk.artifacts.storage_handler import SingleStorageHandler, StorageHandler
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


class MultiHandler(StorageHandler):
    _handlers: list[SingleStorageHandler]
    _default_handler: SingleStorageHandler | None

    def __init__(
        self,
        handlers: list[SingleStorageHandler] | None = None,
        default_handler: SingleStorageHandler | None = None,
    ) -> None:
        self._handlers = handlers or []
        self._default_handler = default_handler

    def _get_handler(self, url: FilePathStr | URIStr) -> SingleStorageHandler:
        parsed_url = urlparse(url)

        valid_handlers = (h for h in self._handlers if h.can_handle(parsed_url))
        if handler := next(valid_handlers, self._default_handler):
            return handler
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
    ) -> Sequence[ArtifactManifestEntry]:
        return self._get_handler(path).store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )
