"""Integration module for automatic Weave initialization with W&B.

This module provides automatic initialization of Weave when:
1. Weave is installed
2. A W&B run is active with a project
3. Either:
   - Weave is imported (init-on-import)
   - An LLM client (OpenAI, Anthropic, etc.) is about to be imported (pre-import init for auto-patching)

The integration can be disabled by setting the WANDB_DISABLE_WEAVE environment variable.
"""

from __future__ import annotations

import os
import sys
import threading
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder

import wandb

_weave_initialized = False
_weave_init_lock = threading.Lock()
_wandb_project: str | None = None
_import_hook_installed = False
_import_finder: MetaPathFinder | None = None

DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
WEAVE_PACKAGE_NAME = "weave"


def _initable() -> bool:
    return bool(_wandb_project and not _weave_initialized)


class _WeaveLoaderWrapper(Loader):
    """Loader wrapper that initializes Weave at the right time.

    - For LLM packages, initializes before executing the module (pre-import).
    - For Weave itself, initializes right after the module is executed (post-import).
    """

    def __init__(self, original_loader: Loader, shortname: str) -> None:
        self._original_loader = original_loader
        self._shortname = shortname

    def create_module(self, spec):  # type: ignore[override]
        if hasattr(self._original_loader, "create_module"):
            return self._original_loader.create_module(spec)
        return None

    def exec_module(self, module):  # type: ignore[override]
        # If disabled, use the default loader
        if os.getenv(DISABLE_WEAVE):
            return self._original_loader.exec_module(module)

        shortname = self._shortname

        # Execute the actual module code
        self._original_loader.exec_module(module)

        # Weave was imported, init it
        if _initable() and (shortname == WEAVE_PACKAGE_NAME):
            _try_init_weave(reason="Weave package detected")


class _WeaveImportFinder(MetaPathFinder):
    """Finder that wraps loaders for weave and supported LLM packages."""

    def find_spec(self, fullname, path, target=None):  # type: ignore[override]
        if os.getenv(DISABLE_WEAVE):
            return None

        # Skip if we don't find packages of interest
        shortname = fullname.split(".")[0]
        if shortname != WEAVE_PACKAGE_NAME:
            return None

        # Delegate to default path finder, then wrap its loader
        spec = PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec

        spec.loader = _WeaveLoaderWrapper(spec.loader, shortname)
        return spec


def _try_init_weave(reason: str = "") -> None:
    """Try to initialize Weave if it's available and not already initialized.

    Args:
        reason: Optional reason for initialization (for logging).
    """
    global _weave_initialized

    # Check if Weave is disabled via environment variable
    if os.getenv(DISABLE_WEAVE):
        return

    if not _initable():
        return

    with _weave_init_lock:
        if not _initable():
            return

        if reason:
            wandb.termlog(f"Initializing weave: {reason}")

        try:
            import weave
        except ImportError:
            pass  # Weave is not installed

        try:
            assert _wandb_project is not None
            weave.init(_wandb_project)
        except Exception as e:
            wandb.termwarn(f"Failed to automatically initialize Weave: {e}")
        else:
            _weave_initialized = True


def setup_weave_integration(project: str | None) -> None:
    """Set up automatic Weave initialization for the current W&B run.

    Args:
        project: The W&B project name to use for Weave initialization.
    """
    global _wandb_project, _import_hook_installed

    # Check if Weave integration is disabled via environment variable
    if os.getenv(DISABLE_WEAVE):
        return

    # Store the project name for later use
    _wandb_project = project

    # Only proceed if project is specified
    if not project:
        return

    # If Weave has already been imported, initialize immediately
    if WEAVE_PACKAGE_NAME in sys.modules:
        _try_init_weave(reason="Weave import detected")

    # Install import hook for future imports
    if not _import_hook_installed:
        global _import_finder
        _import_finder = _WeaveImportFinder()
        sys.meta_path.insert(0, _import_finder)
        _import_hook_installed = True


def cleanup_weave_integration() -> None:
    """Clean up the Weave integration and restore original state."""
    global _weave_initialized, _wandb_project, _import_hook_installed, _import_finder

    # Remove our meta path finder if installed
    if _import_hook_installed and _import_finder is not None:
        try:
            if _import_finder in sys.meta_path:
                sys.meta_path.remove(_import_finder)
        finally:
            _import_hook_installed = False
            _import_finder = None

    # Reset state
    _weave_initialized = False
    _wandb_project = None
