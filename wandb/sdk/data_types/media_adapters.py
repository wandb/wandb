"""Helpers for converting wandb rich media types to Weave-native types for eval logging."""

from __future__ import annotations

import warnings
from typing import Any

import wandb
from wandb.sdk.data_types.base_types.media import Media as _WandbMedia


def unwrap_value(val: Any, column: str, warned: set[type]) -> Any:
    """Convert a wandb media cell value to an appropriate type for Weave logging.

    Args:
        val: Cell value to convert.
        column: Column name used in error/warning messages.
        warned: Set of wandb types already warned about (mutated in-place).

    Returns:
        PIL.Image.Image if val is a wandb.Image (preferred — weave has a dedicated
        image type handler for proper frontend rendering). Falls back to
        weave.Content.from_path if PIL is unavailable.
        Returns val unchanged for non-media types.

    Raises:
        ImportError: If val is a wandb.Image but PIL (and weave.Content) are unavailable.
        TypeError: If val is an unsupported wandb Media subclass.
    """
    if isinstance(val, wandb.Image):
        if wandb.Image not in warned:
            warnings.warn(
                "wandb.Image values are converted to PIL.Image for Weave logging. "
                "Caption and other metadata are discarded.",
                stacklevel=4,
            )
            warned.add(wandb.Image)

        # Try PIL via val.image (lazy property; works for numpy, PIL, and path init modes)
        try:
            from PIL import Image as _PILImage

            pil = val.image
            if pil is not None:
                return pil
            # image property returned None but _path may exist — load explicitly
            if val._path is not None:
                return _PILImage.open(val._path)
        except ImportError:
            pass

        # TODO: Support other data types

        raise ImportError(
            f"Cannot convert wandb.Image in column {column!r} for Weave logging: "
            "install Pillow (pip install pillow) or weave (pip install weave)."
        )

    # TODO: add handlers for wandb.Audio, wandb.Video, and other media types
    if isinstance(val, _WandbMedia):
        raise TypeError(
            f"Unsupported wandb media type {type(val).__name__!r} in column {column!r}. "
            "Only wandb.Image is currently supported."
        )

    return val


def unwrap_row(row: dict[str, Any], warned: set[type]) -> dict[str, Any]:
    """Apply unwrap_value to every value in a row dict."""
    return {k: unwrap_value(v, k, warned) for k, v in row.items()}
