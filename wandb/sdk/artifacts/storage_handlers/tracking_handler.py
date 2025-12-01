"""Tracking storage handler."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from wandb.errors.term import termwarn
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import StorageHandler
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from wandb.sdk.artifacts.artifact import Artifact


class TrackingHandler(StorageHandler):
    _scheme: str

    def __init__(self, scheme: str = "") -> None:
        """Track paths with no modification or special processing.

        Useful when paths being tracked are on file systems mounted at a standardized
        location.

        For example, if the data to track is located on an NFS share mounted on
        `/data`, then it is sufficient to just track the paths.
        """
        self._scheme = scheme

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if local:
            # Likely a user error. The tracking handler is
            # oblivious to the underlying paths, so it has
            # no way of actually loading it.
            url = urlparse(manifest_entry.ref)
            raise ValueError(
                f"Cannot download file at path {str(manifest_entry.ref)}, scheme {str(url.scheme)} not recognized"
            )
        # TODO(spencerpearson): should this go through util.to_native_slash_path
        # instead of just getting typecast?
        return FilePathStr(manifest_entry.path)

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        url = urlparse(path)
        if name is None:
            raise ValueError(
                f'You must pass name="<entry_name>" when tracking references with unknown schemes. ref: {path}'
            )
        termwarn(
            f"Artifact references with unsupported schemes cannot be checksummed: {path}"
        )
        name = name or url.path[1:]  # strip leading slash
        return [ArtifactManifestEntry(path=name, ref=path, digest=path)]
