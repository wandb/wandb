"""Deprecated: Use `wandb.registries` instead.

This module is deprecated and will be removed in a future release.
Please update your imports to use `wandb.registries` directly.
"""

from __future__ import annotations

import warnings

# Re-export from the new location
from wandb.registries import Registry

__all__ = [
    "Registry",
]

_DEPRECATION_MESSAGE = (
    "Imports from 'wandb.apis.public.registries' are deprecated "
    "and will be removed in a future release. "
    "Please use 'wandb.registries' instead. "
)


def _emit_deprecation_warning() -> None:
    """Emit deprecation warning with proper stack level."""
    # stacklevel=3 typically points to the actual import statement:
    # 1 = this function, 2 = module-level code, 3 = the import statement
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=3)


# Emit warning when the module is imported
_emit_deprecation_warning()
