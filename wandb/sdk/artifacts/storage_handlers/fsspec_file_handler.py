"""Storage handler utilizing fsspec."""
import fsspec
import os
import time
from fsspec.registry import available_protocols
from typing import TYPE_CHECKING, Optional, Sequence, Union
from urllib.parse import ParseResult

from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.hashutil import B64MD5, md5_string
from wandb.sdk.lib.paths import FilePathStr, StrPath, URIStr

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact


class FsspecFileHandler(StorageHandler):
    """Handles a variety of different storage solutions."""

    def __init__(self) -> None:
        """Track files or directories on a variety of filesystem.

        A list of all available options can be found under the following link:
        https://github.com/fsspec/filesystem_spec/blob/master/fsspec/registry.py
        """
        self._schemes = available_protocols()
        self._cache = get_artifacts_cache()

    def can_handle(self, parsed_url: "ParseResult") -> bool:
        return parsed_url.scheme in self._schemes

    def load_path(
        self,
        manifest_entry: ArtifactManifestEntry,
        local: bool = False,
    ) -> Union[URIStr, FilePathStr]:
        """Load the file in the specified artifact given its corresponding entry.

        Download the referenced artifact; return the path to the caller.

        Arguments:
            manifest_entry (ArtifactManifestEntry): The index entry to load

        Returns:
            (os.PathLike): A path to the file represented by `index_entry`
        """
        if not local:
            assert manifest_entry.ref is not None
            return manifest_entry.ref

        if manifest_entry.ref is None:
            raise ValueError(f"Cannot add path with no ref: {manifest_entry.path}")
        fs, fs_path = fsspec.core.url_to_fs(str(manifest_entry.ref))

        if not fs.exists(fs_path):
            raise ValueError(
                "fsspec file reference: Failed to find file at path %s" % fs_path
            )

        path, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(manifest_entry.digest),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
        )
        if hit:
            return path

        md5 = fs.checksum(fs_path)
        if md5 != manifest_entry.digest:
            raise ValueError(
                f"fsspec file reference: Digest mismatch for path {manifest_entry.path}: expected {manifest_entry.digest} but found {md5}"
            )

        filesystem.mkdir_exists_ok(os.path.dirname(path))
        fs.get_file(fs_path, path)

        return path

    def store_path(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        # We have a single file or directory
        entries = []
        fs, fs_path = fsspec.core.url_to_fs(path)

        def md5(path: str) -> B64MD5:
            return (
                fs.checksum(path)
                if checksum
                else md5_string(str(fs.info(path)["size"]))
            )

        if fs.isdir(fs_path):
            i = 0
            start_time = time.time()
            if checksum:
                termlog(
                    'Generating checksum for up to %i files in "%s"...\n'
                    % (max_objects, fs_path),
                    newline=False,
                )
            for root, _, files in fs.walk(fs_path):
                for sub_path in files:
                    i += 1
                    if i > max_objects:
                        raise ValueError(
                            "Exceeded %i objects tracked, pass max_objects to add_reference"
                            % max_objects
                        )
                    physical_path = os.path.join(root, sub_path)
                    relative_path = os.path.relpath(physical_path, start=fs_path)
                    if name is not None:
                        relative_path = os.path.join(name, relative_path)

                    entry = ArtifactManifestEntry(
                        path=relative_path,
                        ref=FilePathStr(os.path.join(path, relative_path)),
                        size=fs.info(physical_path)["size"],
                        digest=fs.checksum(physical_path),
                    )
                    entries.append(entry)
            if checksum:
                termlog("Done. %.1fs" % (time.time() - start_time), prefix=False)
        elif fs.isfile(fs_path):
            name = name or os.path.basename(fs_path)
            entry = ArtifactManifestEntry(
                path=name,
                ref=path,
                size=fs.info(fs_path)["size"],
                digest=md5(fs_path),
            )
            entries.append(entry)
        else:
            # TODO: update error message if we don't allow directories.
            raise ValueError('Path "%s" must be a valid file or directory path' % path)
        return entries
