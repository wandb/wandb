"""Keras integration helpers."""

import sys

import wandb
from wandb.util import add_import_hook


def _check_keras_version() -> None:
    from keras import __version__ as keras_version
    from packaging.version import parse

    if parse(keras_version) < parse("2.4.0"):
        wandb.termwarn(
            f"Keras version {keras_version} is not fully supported. Required keras >= 2.4.0"
        )


if "keras" in sys.modules:
    _check_keras_version()
else:
    add_import_hook("keras", _check_keras_version)


def patch_tf_keras() -> None:
    """Retained for supported callbacks that call this before using tf.keras."""
    return None
