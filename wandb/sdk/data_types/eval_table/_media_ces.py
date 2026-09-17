"""Prepare W&B media values for CES-backed EvalTable writes.

This module converts supported media into CES extension values backed by durable
artifact or run-file references. Supported implementations preserve these source
semantics:

* Newly created media is bound to the active run and stored as a run file.
* Media already bound to the active run reuses its run file. Media bound to a
  different run is copied before binding, leaving the original object unchanged.
* Artifact-backed media preserves its committed W&B artifact URI. External
  reference artifacts are unsupported because CES cannot authenticate to them.
"""

from __future__ import annotations

import copy
import hashlib
import os
import pathlib
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote

from wandb import util
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


# Stays under the 3.5 MiB ClickHouse single-row insert limit that Weave adopted
# after larger rows failed in production (wandb/weave#2353, wandb/weave#5448).
CES_MAX_CELL_BYTES = 3_500_000
_CESMediaExtensionValue = dict[str, Any]
CESExtensionType = str
_DIGEST_PATH_LENGTH = 20
_MediaT = TypeVar("_MediaT", bound=Media)
# Intentionally empty in this foundational layer. Later PRs add supported types.
SUPPORTED_WANDB_MEDIA_TYPES: tuple[type[Media], ...] = ()


@dataclass(frozen=True)
class PreparedMediaCell:
    """A CES extension value and its encoded-size metadata for one media cell.

    Media implementations set `value` to `None` when the encoded extension value
    reaches `CES_MAX_CELL_BYTES` while retaining its type and size metadata.
    """

    value: _CESMediaExtensionValue | None
    extension_type: CESExtensionType
    extension_schema_version: int
    encoded_size: int
    oversized: bool


def is_supported_wandb_media(value: Any) -> bool:
    return isinstance(value, SUPPORTED_WANDB_MEDIA_TYPES)


def prepare_media(
    media: Media,
    run: Run,
    eval_table_key: str,
) -> PreparedMediaCell:
    """Prepare supported media for one EvalTable cell in the active run."""
    raise UsageError(
        f"CES EvalTable does not support media type {type(media).__name__!r}."
    )


def _media_for_run(media: _MediaT, run: Run) -> _MediaT:
    if _is_bound_to_another_run(media, run):
        return _unbound_copy(media)
    return media


def _is_bound_to_another_run(media: Media, run: Run) -> bool:
    return media._run is not None and media._run is not run


def _unbound_copy(media: _MediaT) -> _MediaT:
    cloned = copy.copy(media)
    cloned._run = None
    return cloned


def _committed_artifact_ref_url(media: Media) -> str | None:
    ref_url = media._get_artifact_entry_ref_url()
    return ref_url if util._is_artifact_string(ref_url) else None


# Only unbound media may enter the EvalTable run-file namespace. Callers preserve
# committed artifact references and copy cross-run media before binding.
def _bind_eval_table_media_to_run(
    media: Media,
    run: Run,
    eval_table_key: str,
) -> str:
    if media._run is run:
        return _run_file_uri(run, _logical_run_file_path(media, run))

    if media._run is not None:
        raise UsageError(
            f"Cannot rebind {type(media).__name__} from a different run in place."
        )

    if media.path_is_reference(media._path):
        raise ValueError(
            f"{type(media).__name__} media created by a reference to external "
            "storage cannot currently be added to a run"
        )

    if not media.file_is_set():
        raise UsageError(
            f"Cannot log {type(media).__name__} in an EvalTable without a file."
        )

    assert media._path is not None
    assert media._sha256 is not None
    extension = media._extension
    if extension is None:
        _, extension = os.path.splitext(os.path.basename(media._path))

    relative_subdir = os.path.relpath(media.get_media_subdir(), "media")
    safe_eval_table_key = util.make_file_path_upload_safe(str(eval_table_key))
    directory = os.path.join(
        "media", "eval_tables", relative_subdir, safe_eval_table_key
    )
    logical_path = os.path.join(
        directory,
        f"{media._sha256[:_DIGEST_PATH_LENGTH]}{extension}",
    )
    destination = os.path.join(run.dir, logical_path)

    destination_exists = os.path.exists(destination)
    destination_matches = (
        destination_exists and _file_sha256(destination) == media._sha256
    )
    if destination_matches:
        return _bind_to_existing_run_file(media, run, logical_path, destination)

    if destination_exists:
        logical_path = os.path.join(directory, f"{media._sha256}{extension}")
        destination = os.path.join(run.dir, logical_path)
        full_digest_destination_exists = os.path.exists(destination)
        full_digest_destination_matches = (
            full_digest_destination_exists
            and _file_sha256(destination) == media._sha256
        )
        if full_digest_destination_matches:
            return _bind_to_existing_run_file(media, run, logical_path, destination)
        if full_digest_destination_exists:
            # A true SHA-256 collision is about 1 in 2**256, but stale files can
            # produce the same path conflict.
            suffix = 1
            while True:
                logical_path = os.path.join(
                    directory,
                    f"{media._sha256}-{suffix}{extension}",
                )
                destination = os.path.join(run.dir, logical_path)
                if not os.path.exists(destination):
                    break
                if _file_sha256(destination) == media._sha256:
                    return _bind_to_existing_run_file(
                        media, run, logical_path, destination
                    )
                suffix += 1

    filesystem.mkdir_exists_ok(os.path.dirname(destination))
    if media._is_tmp:
        shutil.move(media._path, destination)
        media._is_tmp = False
    elif run._settings.allow_media_symlink:
        filesystem.link_or_copy(
            run._settings,
            pathlib.Path(media._path).resolve(),
            pathlib.Path(destination),
        )
    else:
        shutil.copy(media._path, destination)

    media._run = run
    media._path = destination
    run._publish_file(logical_path)
    return _run_file_uri(run, logical_path)


def _bind_to_existing_run_file(
    media: Media,
    run: Run,
    logical_path: str,
    destination: str,
) -> str:
    media._run = run
    media._path = destination
    media._is_tmp = False
    return _run_file_uri(run, logical_path)


def _logical_run_file_path(media: Media, run: Run) -> LogicalPath:
    if media._path is None:
        raise UsageError(f"Bound {type(media).__name__} has no run file path.")
    return LogicalPath(os.path.relpath(media._path, run.dir))


def _run_file_uri(run: Run, logical_path: str) -> str:
    if not run.entity or not run.project or not run.id:
        raise UsageError("EvalTable media requires an entity, project, and run ID.")
    components = [run.entity, run.project, run.id]
    path_components = LogicalPath(logical_path).parts
    encoded = "/".join(
        quote(str(part), safe="") for part in (*components, *path_components)
    )
    return f"wandb-run-file://{encoded}"


def _file_sha256(path: str) -> str:
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()
