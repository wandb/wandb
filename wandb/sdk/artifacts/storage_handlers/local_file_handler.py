"""Local file storage handler."""

from __future__ import annotations

import os
import shutil
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from urllib.parse import ParseResult

from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib.hashutil import B64MD5, md5_file_b64, md5_string
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr
from wandb.util import local_file_uri_to_path

from ._timing import TimedIf

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


def _md5_content(path: str) -> B64MD5:
    return md5_file_b64(path)


def _md5_path(path: str) -> B64MD5:
    return md5_string(Path(path).resolve().as_uri())


class LocalFileHandler(StorageHandler):
    """Handles file:// references."""

    _scheme: str
    _cache: ArtifactFileCache

    def __init__(self, scheme: str = "file") -> None:
        """Track files or directories on a local filesystem.

        Expand directories to create an entry for each file contained.
        """
        self._scheme = scheme
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: ParseResult) -> bool:
        return parsed_url.scheme == self._scheme

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> URIStr | FilePathStr:
        if (ref_uri := manifest_entry.ref) is None:
            raise ValueError(f"Cannot add path with no ref: {manifest_entry.path}")

        if not os.path.exists(local_path := local_file_uri_to_path(ref_uri)):
            raise ValueError(
                f"Local file reference: Failed to find file at path {local_path!r}"
            )

        expected_digest = manifest_entry.digest

        path, hit, cache_open = self._cache.check_md5_obj_path(
            b64_md5=expected_digest, size=manifest_entry.size or 0
        )
        if hit:
            return path

        if (digest := md5_file_b64(local_path)) != expected_digest:
            raise ValueError(
                f"Local file reference: Digest mismatch for path {local_path!r}: expected {expected_digest!r} but found {digest!r}"
            )

        # Ensure the parent directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with cache_open() as f:
            shutil.copy(local_path, f.name)
        return path

    def store_path(
        self,
        artifact: Artifact,
        path: URIStr | FilePathStr,
        name: StrPath | None = None,
        checksum: bool = True,
        max_objects: int | None = None,
    ) -> list[ArtifactManifestEntry]:
        local_path = local_file_uri_to_path(path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS

        # If checksum=False, the file's hash should only
        # depend on its absolute path/URI, not its contents

        # Closure func for calculating the file hash from its path
        check_md5: Callable[[str], B64MD5] = _md5_content if checksum else _md5_path

        # We have a single file or directory
        # Note, we follow symlinks for files contained within the directory
        if os.path.isdir(local_path):
            entries: deque[ArtifactManifestEntry] = deque()
            with TimedIf(checksum):
                if checksum:
                    termlog(
                        f"Generating checksum for up to {max_objects!r} files in {local_path!r}... ",
                        newline=False,
                    )

                physical_paths = (
                    os.path.join(root, subpath)
                    for root, _, files in os.walk(local_path)
                    for subpath in files
                )
                for i, physical_path in enumerate(physical_paths):
                    if i >= max_objects:
                        raise ValueError(
                            f"Exceeded {max_objects!r} objects tracked, pass max_objects to add_reference"
                        )

                    # TODO(spencerpearson): this is not a "logical path" in the sense that
                    # `LogicalPath` returns a "logical path"; it's a relative path
                    # **on the local filesystem**.
                    file_path = os.path.relpath(physical_path, start=local_path)
                    artifact_path = os.path.join(name or "", file_path)
                    entry = ArtifactManifestEntry(
                        path=artifact_path,
                        ref=os.path.join(path, file_path),
                        size=os.path.getsize(physical_path),
                        digest=check_md5(physical_path),
                    )
                    entries.append(entry)
            return list(entries)

        if os.path.isfile(local_path):
            return [
                ArtifactManifestEntry(
                    path=name or os.path.basename(local_path),
                    ref=path,
                    size=os.path.getsize(local_path),
                    digest=check_md5(local_path),
                )
            ]
        else:
            # TODO: update error message if we don't allow directories.
            raise ValueError(f"Path {path!r} must be a valid file or directory path")
