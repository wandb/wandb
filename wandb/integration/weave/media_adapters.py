"""Helpers for converting wandb rich media types to Weave-native types for eval logging."""

from __future__ import annotations

import hashlib
import importlib
import json
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, get_args

import wandb
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.table import Table

UnsupportedMediaMode = Literal["raise", "stub"]
_UNSUPPORTED_MEDIA_MODES = get_args(UnsupportedMediaMode)
_MOVIEPY_EDITOR_INSTALL_HINT = (
    'Install it with `pip install wandb["eval-table-video-support"]`'
)


def _warn_once(media_type: type, warned: set[type], message: str) -> None:
    if media_type in warned:
        return
    warnings.warn(message, stacklevel=4)
    warned.add(media_type)


def _path_for_local_media(val: Media, column: str) -> Path:
    path = val._path
    if val.path_is_reference(path):
        raise TypeError(
            f"Unsupported external media reference {path!r} in column {column!r}. "
            "EvalTable currently supports local files and in-memory media only."
        )
    if path is None:
        raise TypeError(
            f"Cannot convert {type(val).__name__} in column {column!r}: "
            "media object does not have a local file path."
        )
    return Path(path)


def _unwrap_image(val: wandb.Image, column: str, warned: set[type]) -> Any:
    _warn_once(
        wandb.Image,
        warned,
        "wandb.Image values are converted to PIL.Image for Weave logging. "
        "Caption and other metadata are discarded.",
    )

    if val.path_is_reference(val._path):
        raise TypeError(
            f"Unsupported external media reference {val._path!r} in column {column!r}. "
            "EvalTable currently supports local files and in-memory media only."
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


def _unwrap_audio(val: wandb.Audio, column: str, warned: set[type]) -> Any:
    _warn_once(
        wandb.Audio,
        warned,
        "wandb.Audio values are converted to weave.Audio for Weave logging. "
        "Caption and other metadata are discarded.",
    )

    from weave import Audio as WeaveAudio

    path = _path_for_local_media(val, column)
    try:
        return WeaveAudio.from_path(path)
    except ValueError as e:
        raise TypeError(
            f"Cannot convert wandb.Audio in column {column!r} for Weave logging: {e}"
        ) from e


def _unwrap_video(val: wandb.Video, column: str, warned: set[type]) -> Any:
    _warn_once(
        wandb.Video,
        warned,
        "wandb.Video values are converted to Weave-native video values. "
        "Caption and other metadata are discarded.",
    )

    path = _path_for_local_media(val, column)

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


def _public_wandb_type_name(value_type: type) -> str:
    for name, public_value in vars(wandb).items():
        if public_value is value_type:
            return f"wandb.{name}"
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _format_type_list(value_types: tuple[type, ...]) -> str:
    names = [_public_wandb_type_name(value_type) for value_type in value_types]
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"


_SUPPORTED_WANDB_VALUE_ADAPTERS: dict[type, Callable[[Any, str, set[type]], Any]] = {
    wandb.Image: _unwrap_image,
    wandb.Audio: _unwrap_audio,
    wandb.Video: _unwrap_video,
}
_SUPPORTED_WANDB_VALUE_TYPES = tuple(_SUPPORTED_WANDB_VALUE_ADAPTERS)
_SUPPORTED_WANDB_VALUE_TYPES_MSG = _format_type_list(_SUPPORTED_WANDB_VALUE_TYPES)


def _cell_location(column: str | int, row_idx: int | None = None) -> str:
    if row_idx is None:
        return f"Column {column!r}"
    return f"Cell at row {row_idx}, column {column!r}"


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
    row_idx: int | None = None,
    unsupported_media_mode: UnsupportedMediaMode = "raise",
) -> None:
    """Raise if a wandb value is not supported by EvalTable's Weave adapter."""
    validate_unsupported_media_mode(unsupported_media_mode)

    if isinstance(val, _SUPPORTED_WANDB_VALUE_TYPES):
        return

    location = _cell_location(column, row_idx)

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


def _json_safe_value(val: Any) -> Any:
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    if isinstance(val, (list, tuple)):
        return [_json_safe_value(item) for item in val]
    if isinstance(val, dict):
        return {str(key): _json_safe_value(value) for key, value in val.items()}
    try:
        tolist = val.tolist
    except AttributeError:
        pass
    else:
        try:
            return _json_safe_value(tolist())
        except Exception:
            pass
    return f"<{type(val).__module__}.{type(val).__qualname__}>"


def _json_digest(payload: Any) -> str:
    json_payload = json.dumps(
        _json_safe_value(payload),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(json_payload.encode("utf-8")).hexdigest()


def _unsupported_wandb_value_digest(val: WBValue) -> str:
    if isinstance(val, Media):
        try:
            sha256 = val._sha256
        except AttributeError:
            sha256 = None
        if isinstance(sha256, str) and sha256:
            return sha256

        try:
            path = val._path
        except AttributeError:
            path = None
        if isinstance(path, str) and path:
            if val.path_is_reference(path):
                return _json_digest({"type": type(val).__name__, "ref": path})
            path_obj = Path(path)
            if path_obj.is_file():
                hasher = hashlib.sha256()
                with path_obj.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hasher.update(chunk)
                return hasher.hexdigest()

    try:
        payload = val.to_json(None)  # type: ignore[arg-type]
    except Exception:
        payload = {
            key: value
            for key, value in vars(val).items()
            if key
            not in {
                "_artifact_source",
                "_artifact_target",
                "_run",
                "_path",
            }
        }

    return _json_digest({"type": type(val).__name__, "value": payload})


def _stub_unsupported_wandb_value(val: WBValue, warned: set[type]) -> str:
    _warn_once(
        type(val),
        warned,
        f"wandb.{type(val).__name__} values are not supported by EvalTable yet. "
        "They will be logged as placeholder strings.",
    )
    digest = _unsupported_wandb_value_digest(val)[:8]
    return f"[wandb.{type(val).__name__} unsupported: {digest}]"


def unwrap_value(
    val: Any,
    column: str,
    warned: set[type],
    unsupported_media_mode: UnsupportedMediaMode = "raise",
) -> Any:
    """Convert a wandb media cell value to an appropriate type for Weave logging.

    Args:
        val: Cell value to convert.
        column: Column name used in error/warning messages.
        warned: Set of wandb types already warned about (mutated in-place).

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

    for value_type, adapter in _SUPPORTED_WANDB_VALUE_ADAPTERS.items():
        if isinstance(val, value_type):
            return adapter(val, column, warned)

    if isinstance(val, WBValue):
        return _stub_unsupported_wandb_value(val, warned)

    return val
