"""Helpers for converting wandb rich media types to Weave-native types for eval logging."""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, get_args

import wandb
from wandb.sdk.data_types.audio import Audio
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.image import Image
from wandb.sdk.data_types.table import Table
from wandb.sdk.data_types.video import Video
from wandb.sdk.lib.hashutil import md5_file_b64, md5_string

UnsupportedMediaMode = Literal["stub", "raise"]
_UNSUPPORTED_MEDIA_MODES = get_args(UnsupportedMediaMode)
_UnwrapValueFn = Callable[[Any, str | int], Any]
_SupportedValueAdapter = tuple[str, _UnwrapValueFn]
_MOVIEPY_EDITOR_INSTALL_HINT = (
    'Install it with `pip install wandb["eval-table-video-support"]`'
)


class _UnsupportedMediaVariantError(TypeError):
    """Raised when EvalTable supports a media type but not this representation."""


def _path_for_local_media(val: Media, column: str | int) -> Path:
    path = val._path
    if val.path_is_reference(path):
        raise _UnsupportedMediaVariantError(
            f"EvalTable does not support external media references for "
            f"wandb.{type(val).__name__} in column {column!r}: {path!r}. "
            "EvalTable currently supports local files and in-memory media only."
        )
    if path is None:
        raise _UnsupportedMediaVariantError(
            f"Cannot convert wandb.{type(val).__name__} in column {column!r}: "
            "media object does not have a local file path."
        )
    return Path(path)


def _unwrap_image(val: Image, column: str | int) -> Any:
    if val.path_is_reference(val._path):
        raise _UnsupportedMediaVariantError(
            f"EvalTable does not support external media references for "
            f"wandb.Image in column {column!r}: {val._path!r}. "
            "EvalTable currently supports local files and in-memory media only."
        )

    wandb.termwarn(
        "wandb.Image values are converted to PIL.Image for Weave logging. "
        "Caption and other metadata are discarded.",
        repeat=False,
    )

    try:
        from PIL import Image as _PILImage

        pil = val.image
        if pil is not None:
            return pil
        if val._path is not None:
            return _PILImage.open(val._path)
    except ImportError:
        pass

    raise ImportError(
        f"Cannot convert wandb.Image in column {column!r} for Weave logging: "
        "install Pillow with `pip install pillow` or `pip install wandb[media]`."
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
        editor = importlib.import_module("moviepy.editor")
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
        "To temporarily log hash placeholders instead, pass "
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
    validate_unsupported_media_mode(unsupported_media_mode)

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


def _stable_digest(payload: Any) -> str:
    json_payload = json.dumps(
        payload,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return md5_string(json_payload)


_UNSUPPORTED_WANDB_VALUE_DIGEST_IGNORED_FIELDS = {
    "_artifact_source",
    "_artifact_target",
    "_run",
}


def _unsupported_wandb_value_payload(val: WBValue) -> dict[str, Any]:
    try:
        payload = vars(val).copy()
    except TypeError:
        payload = {}

    for key in _UNSUPPORTED_WANDB_VALUE_DIGEST_IGNORED_FIELDS:
        payload.pop(key, None)

    if isinstance(val, Media):
        path = payload.get("_path")
        if isinstance(path, str) and path and not val.path_is_reference(path):
            path_obj = Path(path)
            if path_obj.is_file():
                payload["_file_digest"] = md5_file_b64(path_obj)
                payload.pop("_path", None)

    return payload


def _unsupported_wandb_value_digest(val: WBValue) -> str:
    # Unsupported WBValue stubs are a temporary fallback. Digest the object's
    # JSON-safe fields without calling to_json(), since many WBValue serializers
    # require a real Run or Artifact.
    return _stable_digest(
        {"type": type(val).__name__, "value": _unsupported_wandb_value_payload(val)}
    )


def _stub_unsupported_wandb_value(val: WBValue) -> str:
    wandb.termwarn(
        f"wandb.{type(val).__name__} values are not supported by EvalTable yet. "
        "They will be logged as placeholder strings.",
        repeat=False,
    )
    digest = _unsupported_wandb_value_digest(val)[:8]
    return f"[wandb.{type(val).__name__} unsupported: {digest}]"


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
            except _UnsupportedMediaVariantError:
                if unsupported_media_mode == "stub":
                    return _stub_unsupported_wandb_value(val)
                raise

    if isinstance(val, WBValue):
        return _stub_unsupported_wandb_value(val)

    return val
