"""Local file storage handler."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import ParseResult

from wandb import util
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.hashutil import B64MD5, md5_file_b64, md5_string
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache


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
        if manifest_entry.ref is None:
            raise ValueError(f"Cannot add path with no ref: {manifest_entry.path}")
        local_path = util.local_file_uri_to_path(str(manifest_entry.ref))
        if not os.path.exists(local_path):
            raise ValueError(
                f"Local file reference: Failed to find file at path {local_path}"
            )

        path, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size or 0,
        )
        if hit:
            return path

        md5 = md5_file_b64(local_path)
        if md5 != manifest_entry.digest:
            raise ValueError(
                f"Local file reference: Digest mismatch for path {local_path}: expected {manifest_entry.digest} but found {md5}"
            )

        filesystem.mkdir_exists_ok(os.path.dirname(path))

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
        local_path = util.local_file_uri_to_path(path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        # We have a single file or directory
        # Note, we follow symlinks for files contained within the directory
        entries = []

        # If checksum=False, the file's hash should only
        # depend on its absolute path/URI, not its contents

        # Closure func for calculating the file hash from its path
        def md5(path: str) -> B64MD5:
            return (
                md5_file_b64(path)
                if checksum
                else md5_string(Path(path).resolve().as_uri())
            )

        if os.path.isdir(local_path):
            i = 0
            start_time = time.monotonic()
            if checksum:
                termlog(
                    f'Generating checksum for up to {max_objects} files in "{local_path}"... ',
                    newline=False,
                )
            for root, _, files in os.walk(local_path):
                for sub_path in files:
                    i += 1
                    if i > max_objects:
                        raise ValueError(
                            f"Exceeded {max_objects} objects tracked, pass max_objects to add_reference"
                        )
                    physical_path = os.path.join(root, sub_path)
                    # TODO(spencerpearson): this is not a "logical path" in the sense that
                    # `LogicalPath` returns a "logical path"; it's a relative path
                    # **on the local filesystem**.
                    file_path = os.path.relpath(physical_path, start=local_path)
                    if name is not None:
                        artifact_path = os.path.join(name, file_path)
                    else:
                        artifact_path = file_path

                    entry = ArtifactManifestEntry(
                        path=artifact_path,
                        ref=FilePathStr(os.path.join(path, file_path)),
                        size=os.path.getsize(physical_path),
                        digest=md5(physical_path),
                    )
                    entries.append(entry)
            if checksum:
                termlog("Done. %.1fs" % (time.monotonic() - start_time), prefix=False)
        elif os.path.isfile(local_path):
            name = name or os.path.basename(local_path)
            entry = ArtifactManifestEntry(
                path=name,
                ref=path,
                size=os.path.getsize(local_path),
                digest=md5(local_path),
            )
            entries.append(entry)
        else:
            # TODO: update error message if we don't allow directories.
            raise ValueError(f'Path "{path}" must be a valid file or directory path')
        return entries
