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
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote

from wandb import util
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


# Stays under the 3.5 MiB ClickHouse single-row insert limit that Weave adopted
# after larger rows failed in production (wandb/weave#2353, wandb/weave#5448).
CES_MAX_CELL_BYTES = 3_500_000
_CESMediaExtensionValue = dict[str, Any]
CESExtensionType = str
_DIGEST_PATH_LENGTH = 30
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


def _media_for_run(media: _MediaT, _run: Run) -> _MediaT:
    return _unbound_copy(media)


def _unbound_copy(media: _MediaT) -> _MediaT:
    cloned = copy.copy(media)
    cloned._run = None
    # The original retains ownership of temporary files, so preparation copies them.
    cloned._is_tmp = False
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
    # A 120-bit prefix has about a 1 in 2.7 quintillion collision chance among
    # one billion files.
    logical_path = os.path.join(
        directory,
        f"{media._sha256[:_DIGEST_PATH_LENGTH]}{extension}",
    )
    media._bind_to_run_path(run, logical_path)
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
