"""Integration module for automatic Weave initialization with W&B.

This module provides automatic initialization of Weave when:
1. Weave is installed
2. A W&B run is active with a project
3. Weave is imported (init-on-import)

The integration can be disabled by setting the WANDB_DISABLE_WEAVE environment variable.
"""

from __future__ import annotations

import os
import sys
import threading

import wandb

_weave_initialized = False
_weave_init_lock = threading.Lock()
_wandb_project: str | None = None

DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
WEAVE_PACKAGE_NAME = "weave"


def setup_weave_integration(entity: str | None, project: str | None) -> None:
    """Set up automatic Weave initialization for the current W&B run.

    Args:
        project: The W&B project name to use for Weave initialization.
    """
    global _wandb_project, _weave_initialized

    # We can't or shouldn't init weave; return
    if os.getenv(DISABLE_WEAVE):
        return
    if _weave_initialized:
        return
    if not project:
        return

    # Use entity/project when available; otherwise fall back to project only
    if entity:
        _wandb_project = f"{entity}/{project}"
    else:
        _wandb_project = project

    # If weave is not yet imported, we can't init it from here.  Instead, we'll
    # rely on the weave library itself to detect a run and init itself.
    if WEAVE_PACKAGE_NAME not in sys.modules:
        return

    # If weave has already been imported, initialize immediately
    with _weave_init_lock:
        if not _wandb_project or _weave_initialized:
            return
        try:
            # This import should have already happened, so it's effectively a no-op.
            # We just import to keep the symbol for the init that follows
            import weave
        except ImportError:
            # This should never happen; but we don't raise here to avoid
            # breaking the wandb run init flow just in case
            return

        wandb.termlog("Initializing weave")
        try:
            weave.init(_wandb_project)
        except Exception as e:
            wandb.termwarn(f"Failed to automatically initialize Weave: {e}")
        else:
            _weave_initialized = True


def cleanup_weave_integration() -> None:
    """Clean up the Weave integration."""
    global _weave_initialized, _wandb_project

    _weave_initialized = False
    _wandb_project = None
