"""Multi storage handler."""

from typing import TYPE_CHECKING, List, Optional, Sequence, Union
from urllib.parse import urlparse

from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.paths import FilePathStr, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry


class MultiHandler(StorageHandler):
    _handlers: List[StorageHandler]

    def __init__(
        self,
        handlers: Optional[List[StorageHandler]] = None,
        default_handler: Optional[StorageHandler] = None,
    ) -> None:
        self._handlers = handlers or []
        self._default_handler = default_handler

    def _get_handler(self, url: Union[FilePathStr, URIStr]) -> StorageHandler:
        parsed_url = urlparse(url)
        for handler in self._handlers:
            if handler.can_handle(parsed_url):
                return handler
        if self._default_handler is not None:
            return self._default_handler
        raise ValueError('No storage handler registered for url "{}"'.format(str(url)))

    def load_path(
        self,
        manifest_entry: "ArtifactManifestEntry",
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        assert manifest_entry.ref is not None
        handler = self._get_handler(manifest_entry.ref)
        return handler.load_path(manifest_entry, local=local)

    def store_path(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence["ArtifactManifestEntry"]:
        handler = self._get_handler(path)
        return handler.store_path(
            artifact, path, name=name, checksum=checksum, max_objects=max_objects
        )
