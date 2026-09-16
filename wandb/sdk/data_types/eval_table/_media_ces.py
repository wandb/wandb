"""Prepare W&B media values for CES-backed EvalTable writes.

This module converts supported media into CES extension values backed by durable
artifact or run-file references.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media

if TYPE_CHECKING:
    from coreweave_evaluations.types.wandb_audio_v1_param import WandbAudioV1Param
    from coreweave_evaluations.types.wandb_image_v1_param import WandbImageV1Param
    from coreweave_evaluations.types.wandb_video_v1_param import WandbVideoV1Param

    from wandb.sdk.wandb_run import Run

    _CESMediaExtensionValue = (
        WandbImageV1Param | WandbAudioV1Param | WandbVideoV1Param
    )


CES_MAX_CELL_BYTES = 3_500_000
_CESExtensionType = Literal["wandb-image", "wandb-audio", "wandb-video"]
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
