"""Local file storage handler."""

import os
import shutil
import time
from typing import TYPE_CHECKING, Optional, Sequence, Union
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


class LocalFileHandler(StorageHandler):
    """Handles file:// references."""

    def __init__(self, scheme: Optional[str] = None) -> None:
        """Track files or directories on a local filesystem.

        Expand directories to create an entry for each file contained.
        """
        self._scheme = scheme or "file"
        self._cache = get_artifact_file_cache()

    def can_handle(self, parsed_url: "ParseResult") -> bool:
        return parsed_url.scheme == self._scheme

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        if manifest_entry.ref is None:
            raise ValueError(f"Cannot add path with no ref: {manifest_entry.path}")
        local_path = util.local_file_uri_to_path(str(manifest_entry.ref))
        if not os.path.exists(local_path):
            raise ValueError(
                "Local file reference: Failed to find file at path {}".format(
                    local_path
                )
            )

        path, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
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
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        local_path = util.local_file_uri_to_path(path)
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        # We have a single file or directory
        # Note, we follow symlinks for files contained within the directory
        entries = []

        def md5(path: str) -> B64MD5:
            return (
                md5_file_b64(path)
                if checksum
                else md5_string(str(os.stat(path).st_size))
            )

        if os.path.isdir(local_path):
            i = 0
            start_time = time.time()
            if checksum:
                termlog(
                    'Generating checksum for up to %i files in "%s"...\n'
                    % (max_objects, local_path),
                    newline=False,
                )
            for root, _, files in os.walk(local_path):
                for sub_path in files:
                    i += 1
                    if i > max_objects:
                        raise ValueError(
                            "Exceeded %i objects tracked, pass max_objects to add_reference"
                            % max_objects
                        )
                    physical_path = os.path.join(root, sub_path)
                    # TODO(spencerpearson): this is not a "logical path" in the sense that
                    # `LogicalPath` returns a "logical path"; it's a relative path
                    # **on the local filesystem**.
                    logical_path = os.path.relpath(physical_path, start=local_path)
                    if name is not None:
                        logical_path = os.path.join(name, logical_path)

                    entry = ArtifactManifestEntry(
                        path=logical_path,
                        ref=FilePathStr(os.path.join(path, logical_path)),
                        size=os.path.getsize(physical_path),
                        digest=md5(physical_path),
                    )
                    entries.append(entry)
            if checksum:
                termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
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
            raise ValueError(
                'Path "{}" must be a valid file or directory path'.format(path)
            )
        return entries
