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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


# Stays under the 3.5 MiB ClickHouse single-row insert limit that Weave adopted
# after larger rows failed in production (wandb/weave#2353, wandb/weave#5448).
CES_MAX_CELL_BYTES = 3_500_000
_CESMediaExtensionValue = dict[str, Any]
_CESExtensionType = str
# Intentionally empty in this foundational layer. Later PRs add supported types.
SUPPORTED_WANDB_MEDIA_TYPES: tuple[type[Media], ...] = ()


@dataclass(frozen=True)
class PreparedMediaCell:
    """A CES extension value and its encoded-size metadata for one media cell.

    Media implementations set `value` to `None` when the encoded extension value
    reaches `CES_MAX_CELL_BYTES` while retaining its type and size metadata.
    """

    value: _CESMediaExtensionValue | None
    extension_type: _CESExtensionType
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
