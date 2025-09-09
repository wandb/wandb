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

_weave_init_lock = threading.Lock()

_DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
_WEAVE_PACKAGE_NAME = "weave"


def setup(entity: str | None, project: str | None) -> None:
    """Set up automatic Weave initialization for the current W&B run.

    Args:
        project: The W&B project name to use for Weave initialization.
    """
    # We can't or shouldn't init weave; return
    if os.getenv(_DISABLE_WEAVE):
        return
    if not project:
        return

    # Use entity/project when available; otherwise fall back to project only
    if entity:
        project_path = f"{entity}/{project}"
    else:
        project_path = project

    # If weave is not yet imported, we can't init it from here.  Instead, we'll
    # rely on the weave library itself to detect a run and init itself.
    if _WEAVE_PACKAGE_NAME not in sys.modules:
        return

    # If weave has already been imported, initialize immediately
    with _weave_init_lock:
        try:
            # This import should have already happened, so it's effectively a no-op.
            # We just import to keep the symbol for the init that follows
            import weave
        except ImportError:
            # This should never happen; but we don't raise here to avoid
            # breaking the wandb run init flow just in case
            return

        wandb.termlog("Initializing weave.")
        try:
            weave.init(project_path)
        except Exception as e:
            wandb.termwarn(f"Failed to automatically initialize Weave: {e}")
