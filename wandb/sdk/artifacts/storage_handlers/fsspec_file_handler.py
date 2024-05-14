"""Storage handler utilizing fsspec."""
import os
import time
from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple, Union
from urllib.parse import ParseResult, parse_qsl, urlparse

from wandb import util
from wandb.errors.term import termlog
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.storage_handler import DEFAULT_MAX_OBJECTS, StorageHandler
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.hashutil import B64MD5, md5_string
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath, URIStr

if TYPE_CHECKING:
    import fsspec  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact


class FsspecFileHandler(StorageHandler):
    """Handles a variety of different storage solutions."""

    def __init__(self) -> None:
        """Track files or directories on a variety of filesystem.

        For now, this handler supports oss (Alibaba Object Storage System)
        A list of all available options can be found under the following link:
        https://github.com/fsspec/filesystem_spec/blob/master/fsspec/registry.py
        """
        self._fsspec = None
        self._cache = get_artifact_file_cache()

    def init_fsspec(self) -> "fsspec":
        if self._fsspec is not None:
            return self._fsspec
        self._fsspec: fsspec = util.get_module(
            "fsspec",
            required="Your selected URI requires the fsspec library, run pip install wandb[fsspec]",
            lazy=False,
        )
        return self._fsspec

    def can_handle(self, parsed_url: "ParseResult") -> bool:
        self.init_fsspec()
        return parsed_url.scheme in self._fsspec.available_protocols()

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
        self.init_fsspec()
        assert self._fsspec is not None  # mypy: unwraps optionality
        assert manifest_entry.ref is not None
        if not local:
            return manifest_entry.ref

        padded_checksum = manifest_entry.digest + "=" * (
            4 - len(manifest_entry.digest) % 4
        )

        path, hit, cache_open = self._cache.check_md5_obj_path(
            B64MD5(padded_checksum),  # TODO(spencerpearson): unsafe cast
            manifest_entry.size if manifest_entry.size is not None else 0,
        )
        if hit:
            return path

        fs, fs_path = self._fsspec.core.url_to_fs(str(manifest_entry.ref))

        if not fs.exists(fs_path):
            raise FileNotFoundError(
                "fsspec file reference: Failed to find file at path %s" % fs_path
            )

        md5 = str(fs.checksum(fs_path))
        if md5 != manifest_entry.digest:
            raise ValueError(
                f"fsspec file reference: Digest mismatch for path {manifest_entry.path}: expected {manifest_entry.digest} but found {md5}"
            )

        filesystem.mkdir_exists_ok(os.path.dirname(path))

        with cache_open() as f:
            fs.get_file(fs_path, f.name)

        return path

    def _parse_uri(self, uri: str) -> Tuple[str, str, str, Optional[str]]:
        url = urlparse(uri)
        query = dict(parse_qsl(url.query))

        bucket = url.netloc
        key = url.path[1:]  # strip leading slash
        version = query.get("versionId")
        schema = url.scheme

        return schema, bucket, key, version

    def store_path(
        self,
        artifact: "Artifact",
        path: Union[URIStr, FilePathStr],
        name: Optional[StrPath] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ) -> Sequence[ArtifactManifestEntry]:
        self.init_fsspec()
        assert self._fsspec is not None  # mypy: unwraps optionality

        # The passed in path might have query string parameters.
        # We only need to care about a subset, like version, when
        # parsing. Once we have that, we can store the rest of the
        # metadata in the artifact entry itself.
        schema, bucket, key, _ = self._parse_uri(path)
        path = URIStr(f"{schema}://{bucket}/{key}")

        max_objects = max_objects or DEFAULT_MAX_OBJECTS
        if not checksum:
            entry_path = name or (key if key != "" else bucket)
            return [ArtifactManifestEntry(path=entry_path, ref=path, digest=path)]

        # We have a single file or directory
        entries = []
        fs, fs_path = self._fsspec.core.url_to_fs(path)

        def md5(path: str) -> Any:
            return (
                fs.checksum(path)
                if checksum
                else md5_string(str(fs.info(path)["size"]))
            )

        if fs.isdir(fs_path):
            start_time = time.time()
            if checksum:
                termlog(
                    'Generating checksum for up to %i files in "%s"...\n'
                    % (max_objects, fs_path),
                    newline=False,
                )
            for root, _, files in fs.walk(fs_path):
                for sub_path in files:
                    if len(entries) == max_objects:
                        raise ValueError(
                            "Exceeded %i objects tracked, pass max_objects to add_reference"
                            % max_objects
                        )
                    physical_path = os.path.join(root, sub_path)
                    relative_path = os.path.relpath(physical_path, start=fs_path)
                    if name is not None:
                        relative_path = os.path.join(name, relative_path)

                    entry = ArtifactManifestEntry(
                        path=LogicalPath(relative_path),
                        ref=FilePathStr(f"{path}/{relative_path}"),
                        size=fs.info(physical_path)["size"],
                        digest=str(md5(physical_path)),
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
                digest=str(md5(fs_path)),
            )
            entries.append(entry)
        else:
            # TODO: update error message if we don't allow directories.
            raise ValueError('Path "%s" must be a valid file or directory path' % path)
        return entries
