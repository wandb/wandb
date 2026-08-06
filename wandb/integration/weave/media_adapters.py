"""Helpers for converting wandb rich media types to Weave-native types for eval logging."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args

import wandb
from wandb.sdk.data_types.audio import Audio
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.image import Image
from wandb.sdk.data_types.table import Table
from wandb.sdk.data_types.video import Video

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

UnsupportedMediaMode = Literal["stub", "raise"]
_UNSUPPORTED_MEDIA_MODES = get_args(UnsupportedMediaMode)
_UnwrapValueFn = Callable[[Any, str | int], Any]
_SupportedValueAdapter = tuple[str, _UnwrapValueFn]
_MOVIEPY_EDITOR_INSTALL_HINT = (
    'Install it with `pip install wandb["eval-table-video-support"]`'
)


class _UnsupportedMediaVariantError(TypeError):
    """Raised when EvalTable supports a media type but not this representation."""

    def __init__(self, message: str, *, stub_warning: str, stub_value: str) -> None:
        super().__init__(message)
        self.stub_warning = stub_warning
        self.stub_value = stub_value


def _path_for_local_media(val: Media, column: str | int) -> Path:
    path = val._path
    if Media.path_is_reference(path):
        type_name = type(val).__name__
        raise _UnsupportedMediaVariantError(
            f"EvalTable does not support external media references for "
            f"wandb.{type(val).__name__} in column {column!r}: {path!r}. "
            "EvalTable currently supports local files and in-memory media only. "
            f"{_unsupported_media_mode_hint()}",
            stub_warning=(
                f"External media references for wandb.{type_name} are not yet "
                "supported by EvalTable. They will be logged as placeholder strings."
            ),
            stub_value=f"[wandb.{type_name} external reference not yet supported]",
        )
    if path is None:
        raise TypeError(
            f"Cannot convert wandb.{type(val).__name__} in column {column!r}: "
            "media object does not have a local file path."
        )
    return Path(path)


def _unwrap_image(val: Image, column: str | int) -> PILImage:
    image = val.image  # loads from memory or local path
    if image is not None:
        wandb.termwarn(
            "wandb.Image values are converted to PIL.Image for Weave logging. "
            "Caption and other metadata are discarded.",
            repeat=False,
        )
        return image

    raise _UnsupportedMediaVariantError(
        f"Unsupported external media reference in column {column!r}. "
        "EvalTable currently supports local files and in-memory media only. "
        f"{_unsupported_media_mode_hint()}",
        stub_warning=(
            "External media references for wandb.Image are not yet supported by "
            "EvalTable. They will be logged as placeholder strings."
        ),
        stub_value="[wandb.Image external reference not yet supported]",
    )


def _unwrap_audio(val: Audio, column: str | int) -> Any:
    path = _path_for_local_media(val, column)

    wandb.termwarn(
        "wandb.Audio values are converted to weave.Audio for Weave logging. "
        "Caption and other metadata are discarded.",
        repeat=False,
    )

    from weave import Audio as WeaveAudio

    try:
        return WeaveAudio.from_path(path)
    except ValueError as e:
        raise TypeError(
            f"Cannot convert wandb.Audio in column {column!r} for Weave logging: {e}"
        ) from e


def _unwrap_video(val: Video, column: str | int) -> Any:
    path = _path_for_local_media(val, column)

    wandb.termwarn(
        "wandb.Video values are converted to Weave-native video values. "
        "Caption and other metadata are discarded.",
        repeat=False,
    )

    VideoFileClip = _moviepy_video_file_clip_class()  # noqa: N806
    return VideoFileClip(str(path))


def _moviepy_video_file_clip_class() -> Any:
    try:
        import moviepy.editor as editor
    except ImportError as e:
        raise ImportError(
            "`wandb.EvalTable` requires a moviepy version that provides "
            f"`moviepy.editor` to convert wandb.Video. {_MOVIEPY_EDITOR_INSTALL_HINT}"
        ) from e

    try:
        return editor.VideoFileClip
    except AttributeError as e:
        raise ImportError(
            "`wandb.EvalTable` requires a moviepy version that provides "
            "`moviepy.editor.VideoFileClip` to convert wandb.Video. "
            f"{_MOVIEPY_EDITOR_INSTALL_HINT}"
        ) from e


def _format_type_list(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"


_SUPPORTED_WANDB_VALUE_ADAPTERS: dict[type, _SupportedValueAdapter] = {
    Image: ("wandb.Image", _unwrap_image),
    Audio: ("wandb.Audio", _unwrap_audio),
    Video: ("wandb.Video", _unwrap_video),
}
_SUPPORTED_WANDB_VALUE_TYPES = tuple(_SUPPORTED_WANDB_VALUE_ADAPTERS)
_SUPPORTED_WANDB_VALUE_TYPES_MSG = _format_type_list(
    [display_name for display_name, _ in _SUPPORTED_WANDB_VALUE_ADAPTERS.values()]
)


def _unsupported_media_mode_hint() -> str:
    return (
        "To temporarily log placeholder strings instead, pass "
        "unsupported_media_mode='stub' to wandb.EvalTable constructor"
    )


def validate_unsupported_media_mode(mode: str) -> None:
    if mode not in _UNSUPPORTED_MEDIA_MODES:
        raise ValueError(
            "unsupported_media_mode must be one of "
            f"{_UNSUPPORTED_MEDIA_MODES}, got {mode!r}."
        )


def validate_supported_value(
    val: Any,
    column: str | int,
    unsupported_media_mode: UnsupportedMediaMode,
) -> None:
    """Raise if a wandb value is not supported by EvalTable's Weave adapter."""
    if isinstance(val, _SUPPORTED_WANDB_VALUE_TYPES):
        return

    location = f"Column {column!r}"

    if isinstance(val, Table):
        raise TypeError(
            f"{location} contains a {type(val).__name__}; "
            "EvalTable does not support nested Tables (or EvalTables) as cell values."
        )

    if isinstance(val, Media):
        if unsupported_media_mode == "stub":
            return
        raise TypeError(
            f"{location} contains unsupported wandb media type "
            f"{type(val).__name__!r}. "
            f"Only {_SUPPORTED_WANDB_VALUE_TYPES_MSG} are currently supported. "
            f"{_unsupported_media_mode_hint()}"
        )

    if isinstance(val, WBValue):
        if unsupported_media_mode == "stub":
            return
        raise TypeError(
            f"{location} contains unsupported wandb value type "
            f"{type(val).__name__!r}. "
            f"Only {_SUPPORTED_WANDB_VALUE_TYPES_MSG} are currently supported. "
            f"{_unsupported_media_mode_hint()}"
        )


def _stub_unsupported_wandb_value(val: WBValue) -> str:
    wandb.termwarn(
        f"wandb.{type(val).__name__} values are not yet supported by EvalTable. "
        "They will be logged as placeholder strings.",
        repeat=False,
    )
    return f"[wandb.{type(val).__name__} not yet supported]"


def _stub_unsupported_nested_wandb_value(val: WBValue) -> str:
    type_name = type(val).__name__
    wandb.termwarn(
        f"Nested wandb.{type_name} values are not yet supported by EvalTable. "
        "They will be logged as placeholder strings.",
        repeat=False,
    )
    return f"[wandb.{type_name} nested value not yet supported]"


def _raise_unsupported_nested_wandb_value(
    val: WBValue,
    column: str | int,
) -> None:
    raise TypeError(
        f"Column {column!r} contains nested wandb value type "
        f"{type(val).__name__!r}. EvalTable does not yet support wandb "
        "media/value types inside lists or tuples. "
        f"{_unsupported_media_mode_hint()}"
    )


def _stub_unsupported_media_variant(
    error: _UnsupportedMediaVariantError,
    val: WBValue,
) -> str:
    wandb.termwarn(error.stub_warning, repeat=False)
    return error.stub_value


def handle_nested_wandb_values(
    val: Any,
    column: str | int,
    unsupported_media_mode: UnsupportedMediaMode,
    *,
    nested: bool = False,
    inside_sequence: bool = False,
) -> Any:
    # TODO: Add first-class support for wandb values nested inside lists/tuples
    # once Weave and the frontend support rendering them inside sequence values.
    if nested and isinstance(val, Table):
        raise TypeError(
            f"Column {column!r} contains a nested {type(val).__name__}; "
            "EvalTable does not support nested Tables (or EvalTables) inside "
            "container values."
        )

    if nested and isinstance(val, WBValue):
        if not inside_sequence:
            return unwrap_value(
                val,
                column,
                unsupported_media_mode=unsupported_media_mode,
            )
        if unsupported_media_mode == "stub":
            return _stub_unsupported_nested_wandb_value(val)
        _raise_unsupported_nested_wandb_value(val, column)

    if isinstance(val, dict):
        return {
            key: handle_nested_wandb_values(
                value,
                column,
                unsupported_media_mode,
                nested=True,
                inside_sequence=inside_sequence,
            )
            for key, value in val.items()
        }
    if isinstance(val, (list, tuple)):
        return [
            handle_nested_wandb_values(
                item,
                column,
                unsupported_media_mode,
                nested=True,
                inside_sequence=True,
            )
            for item in val
        ]

    return val


def unwrap_value(
    val: Any,
    column: str | int,
    unsupported_media_mode: UnsupportedMediaMode,
) -> Any:
    """Convert a wandb media cell value to an appropriate type for Weave logging.

    Args:
        val: Cell value to convert.
        column: Column name used in error/warning messages.
        unsupported_media_mode: How to handle unsupported wandb media/value types.

    Returns:
        PIL.Image.Image for wandb.Image, weave.Audio for supported wandb.Audio
        values, MoviePy VideoFileClip for wandb.Video, placeholder strings for
        unsupported wandb values when unsupported_media_mode is "stub", and val
        unchanged for non-wandb value types.

    Raises:
        ImportError: If the conversion requires an unavailable optional dependency.
        TypeError: If val is an unsupported wandb value type.
    """
    # TODO: Temporarily support wandb.Image, wandb.Audio, and wandb.Video by just
    # converting the data to what weave supports. In the near future, we will instead
    # directly support these types, including all metadata, by registering weave type
    # handlers.
    validate_supported_value(
        val,
        column,
        unsupported_media_mode=unsupported_media_mode,
    )

    for value_type, (_, adapter) in _SUPPORTED_WANDB_VALUE_ADAPTERS.items():
        if isinstance(val, value_type):
            try:
                return adapter(val, column)
            except _UnsupportedMediaVariantError as e:
                if unsupported_media_mode == "stub":
                    return _stub_unsupported_media_variant(e, val)
                raise

    if isinstance(val, WBValue):
        return _stub_unsupported_wandb_value(val)

    return val
