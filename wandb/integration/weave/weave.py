"""Integration module for automatic Weave initialization with W&B.

This module provides automatic initialization of Weave when:
1. Weave is installed
2. A W&B run is active with a project
3. Weave is imported (init-on-import)

The integration can be disabled by setting the WANDB_DISABLE_WEAVE environment variable.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from types import ModuleType

from packaging.version import parse as parse_version

import wandb

_weave_init_lock = threading.Lock()

_DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
_WEAVE_PACKAGE_NAME = "weave"


def _is_weave_disabled() -> bool:
    return bool(os.getenv(_DISABLE_WEAVE))


def build_project_path(entity: str | None, project: str | None) -> str | None:
    if not project:
        return None
    return f"{entity}/{project}" if entity else project


# This list is adapted from https://github.com/wandb/weave/blob/master/weave/integrations/__init__.py
_AVAILABLE_WEAVE_INTEGRATIONS = [
    "anthropic",
    "autogen",
    "cohere",
    "crewai",
    "dspy",
    "google.genai",
    "groq",
    "huggingface_hub.inference",
    "instructor",
    "langchain",
    "litellm",
    "llama_index",
    "mcp",
    "mistral",
    "notdiamond",
    "openai",
    "agents",
    "smolagents",
    "verdict",
    "verifiers",
    "vertexai",
]


def init_weave_if_imported(entity: str | None, project: str | None) -> None:
    """Initialize Weave for the current W&B run if weave is already imported.

    Args:
        entity: The W&B entity name to use for Weave initialization.
        project: The W&B project name to use for Weave initialization.
    """
    if _is_weave_disabled():
        return
    project_path = build_project_path(entity, project)
    if not project_path:
        return

    # If weave is not yet imported, we can't init it from here.  Instead, we'll
    # rely on the weave library itself to detect a run and init itself.
    if _WEAVE_PACKAGE_NAME not in sys.modules:
        _maybe_suggest_weave_installation()
        return

    # If weave has already been imported, initialize immediately
    wandb.termlog("Initializing weave.")
    try:
        _weave_init(project_path)
    except Exception as e:
        wandb.termwarn(f"Failed to automatically initialize weave: {e}")


def import_weave() -> ModuleType:
    """Import weave, translating missing-package errors for W&B callers."""
    try:
        import weave
    except ModuleNotFoundError as e:
        raise ImportError(
            "weave is not installed. Install it with: pip install weave"
        ) from e
    return weave


def check_weave_version(
    weave: ModuleType,
    min_version: str,
) -> str:
    """Raise if the given weave module is older than min_version."""
    try:
        weave_version = weave.__version__
    except AttributeError as e:
        raise ImportError(
            f"weave>={min_version}, but the imported weave package has no __version__"
        ) from e

    if parse_version(weave_version) < parse_version(min_version):
        raise ImportError(f"weave>={min_version}; found weave=={weave_version}")
    return weave_version


def init_weave(
    entity: str | None,
    project: str | None,
) -> bool:
    """Initialize weave for a W&B entity/project.

    Returns:
        False if WANDB_DISABLE_WEAVE is set (caller should surface this).
        True otherwise.

    Raises:
        ImportError: If weave is not installed.
        ValueError: If no project is available, or if weave is already initialized
            for a different project.
    """
    if _is_weave_disabled():
        return False

    project_path = build_project_path(entity, project)
    if not project_path:
        raise ValueError("init_weave requires a project to initialize weave.")

    try:
        _weave_init(project_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            "weave is not installed. Install it with: pip install weave"
        ) from e
    return True


def _maybe_suggest_weave_installation() -> None:
    """Suggest Weave installation or import if any target library is imported."""
    imported_libs = [lib for lib in _AVAILABLE_WEAVE_INTEGRATIONS if lib in sys.modules]
    if not imported_libs:
        return

    weave_spec = importlib.util.find_spec(_WEAVE_PACKAGE_NAME)
    if weave_spec is None:
        # Weave is not installed
        msg = (
            "Use W&B Weave for improved LLM call tracing. Install Weave with "
            "`pip install weave` then add `import weave` to the top of your script."
        )
    else:
        # Weave is installed but not imported
        msg = (
            "Use W&B Weave for improved LLM call tracing. Weave is installed "
            "but not imported. Add `import weave` to the top of your script."
        )

    wandb.termlog(f"Detected [{', '.join(imported_libs)}] in use.", repeat=False)
    wandb.termlog(msg, repeat=False)
    wandb.termlog(
        "For more information, check out the docs at: https://weave-docs.wandb.ai",
        repeat=False,
    )


def _weave_init(project_path: str) -> None:
    """Call weave.init(). May trigger the first import of weave.

    Patched in tests.
    """
    # Lock because weave.init() is not thread-safe.
    with _weave_init_lock:
        import weave

        # Skip re-init if the user already called weave.init() for this project.
        # get_client landed in weave 0.51.54; fall through on older versions.
        #
        # TODO: Remove the AttributeError guard once we set a minimum weave version as a
        # required dependency.
        try:
            client = weave.get_client()
            if client is not None:
                client_project_path = build_project_path(client.entity, client.project)
                if client.ensure_project_exists and client_project_path == project_path:
                    return
                if client_project_path != project_path:
                    raise ValueError(
                        "Weave is already initialized for "
                        f"{client_project_path!r}; cannot initialize it for "
                        f"{project_path!r}."
                    )
        except AttributeError:
            pass

        weave.init(project_path)
