"""Integration module for automatic Weave initialization with W&B.

This module provides automatic initialization of Weave when:
1. Weave is installed
2. A W&B run is active with a project
3. Weave is imported (init-on-import)

The integration can be disabled by setting the WANDB_DISABLE_WEAVE environment variable
to a truthy value.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading

from packaging.version import parse as parse_version

import wandb
from wandb.env import strtobool
from wandb.errors import UsageError

_weave_init_lock = threading.Lock()

_DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
_WEAVE_PACKAGE_NAME = "weave"


def _is_weave_disabled() -> bool:
    value = os.getenv(_DISABLE_WEAVE)
    if value is None:
        return False
    try:
        return strtobool(value)
    except ValueError:
        return False


def build_project_path(entity: str | None, project: str | None) -> str | None:
    if not project:
        return None
    if not entity:
        return project

    return f"{entity}/{project}"


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


def ensure_version(
    min_version: str,
    error_msg: str | None = None,
) -> None:
    """Imports weave and raises if it's not at least the provided version.

    Args:
        min_version: Must import weave with at least this version.
        error_msg: Custom error message if we fail to import min_version. Should be
            capitalized but not end in punctuation.

    Raises:
        ImportError: If we did not successfully import at least min_version.
    """
    message = error_msg or f"weave>={min_version} required"

    try:
        import weave

        weave_version = weave.__version__
    except ModuleNotFoundError as e:
        raise ImportError(message) from e
    except AttributeError as e:
        raise ImportError(message) from e

    if parse_version(weave_version) < parse_version(min_version):
        raise ImportError(f"{message}; found weave=={weave_version}")


def init_weave(
    entity: str | None,
    project: str | None,
) -> None:
    """Initialize weave for a W&B entity/project.

    Raises:
        UsageError: If no project is available, if weave is already initialized
            for a different project, or If WANDB_DISABLE_WEAVE is set.
    """
    if _is_weave_disabled():
        raise UsageError("weave is required, but WANDB_DISABLE_WEAVE is true.")

    project_path = build_project_path(entity, project)
    if not project_path:
        raise UsageError("init_weave requires a project to initialize weave.")

    # Assumes you've already called ensure_version as needed, so any exceptions will
    # just pass through.
    _weave_init(project_path)


def _should_init_weave(project_path: str) -> bool:
    import weave

    try:
        ensure_version("0.51.54")
    except ImportError:
        has_get_client = False
    else:
        has_get_client = True

    # get_client landed in weave 0.51.54; fall through and try initializing on older
    # versions.
    if has_get_client:
        # Skip re-init if the user already called weave.init() for this project.
        client = weave.get_client()
        if client is not None:
            client_project_path = build_project_path(client.entity, client.project)
            if client_project_path != project_path:
                raise UsageError(
                    "Weave is already initialized for "
                    f"{client_project_path!r}; cannot initialize it for "
                    f"{project_path!r}."
                )
            if client.ensure_project_exists:
                # Already initialized. No-op.
                return False

    return True


def _weave_init(project_path: str) -> None:
    """Call weave.init(). May trigger the first import of weave.

    Patched in tests.
    """
    # Lock because weave.init() is not thread-safe.
    with _weave_init_lock:
        import weave

        if _should_init_weave(project_path):
            weave.init(project_path)
