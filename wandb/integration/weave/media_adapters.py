"""Helpers for converting wandb rich media types to Weave-native types for eval logging."""

from __future__ import annotations

import importlib
import sys
import types
import warnings
from pathlib import Path
from typing import Any

import wandb
from wandb.sdk.data_types.base_types.media import Media as _WandbMedia


def _warn_once(media_type: type, warned: set[type], message: str) -> None:
    if media_type in warned:
        return
    warnings.warn(message, stacklevel=4)
    warned.add(media_type)


def _path_for_local_media(val: _WandbMedia, column: str) -> Path:
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

    try:
        from weave import Audio as WeaveAudio  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "`wandb.EvalTable` requires the `weave` package to convert wandb.Audio. "
            "Install it with `pip install weave`."
        ) from e

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

    VideoFileClip = _moviepy_class("VideoFileClip")  # noqa: N806
    _ensure_weave_video_serializer_registered()

    return VideoFileClip(str(path))


def _moviepy_class(name: str) -> Any:
    try:
        editor = importlib.import_module("moviepy.editor")
    except ImportError:
        editor = _install_moviepy_editor_compat()

    try:
        return getattr(editor, name)
    except AttributeError as e:
        raise ImportError(
            "`wandb.EvalTable` requires moviepy to convert wandb.Video. "
            "Install it with `pip install moviepy` or `pip install wandb[media]`."
        ) from e


def _ensure_weave_video_serializer_registered() -> None:
    try:
        from weave.type_handlers.Video import (  # type: ignore[import-not-found]
            video as weave_video,
        )
    except ImportError as e:
        raise ImportError(
            "`wandb.EvalTable` requires the `weave` package to convert wandb.Video. "
            "Install it with `pip install weave`."
        ) from e

    weave_video._ensure_registered()


def _install_moviepy_editor_compat() -> types.ModuleType:
    """Provide moviepy.editor for Weave when MoviePy exposes v2 top-level APIs."""
    try:
        moviepy = importlib.import_module("moviepy")
        editor = types.ModuleType("moviepy.editor")
        editor.VideoClip = moviepy.VideoClip
        editor.VideoFileClip = moviepy.VideoFileClip
    except (ImportError, AttributeError) as e:
        raise ImportError(
            "`wandb.EvalTable` requires moviepy to convert wandb.Video. "
            "Install it with `pip install moviepy` or `pip install wandb[media]`."
        ) from e

    sys.modules["moviepy.editor"] = editor
    return editor


def unwrap_value(val: Any, column: str, warned: set[type]) -> Any:
    """Convert a wandb media cell value to an appropriate type for Weave logging.

    Args:
        val: Cell value to convert.
        column: Column name used in error/warning messages.
        warned: Set of wandb types already warned about (mutated in-place).

    Returns:
        PIL.Image.Image for wandb.Image, weave.Audio for supported wandb.Audio
        values, and MoviePy VideoFileClip for wandb.Video.
        Returns val unchanged for non-media types.

    Raises:
        ImportError: If the conversion requires an unavailable optional dependency.
        TypeError: If val is an unsupported wandb Media subclass.
    """
    # TODO: Temporarily support wandb.Image, wandb.Audio, and wandb.Video by just
    # converting the data to what weave supports. In the near future, we will instead
    # directly support these types, including all metadata, by registering weave type
    # handlers.
    if isinstance(val, wandb.Image):
        return _unwrap_image(val, column, warned)

    if isinstance(val, wandb.Audio):
        return _unwrap_audio(val, column, warned)

    if isinstance(val, wandb.Video):
        return _unwrap_video(val, column, warned)

    if isinstance(val, _WandbMedia):
        raise TypeError(
            f"Unsupported wandb media type {type(val).__name__!r} in column {column!r}. "
            "Only wandb.Image, wandb.Audio, and wandb.Video are currently supported."
        )

    return val
