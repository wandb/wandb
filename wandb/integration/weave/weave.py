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

import wandb

_weave_init_lock = threading.Lock()

_DISABLE_WEAVE = "WANDB_DISABLE_WEAVE"
_WEAVE_PACKAGE_NAME = "weave"

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
        _maybe_suggest_weave_installation()
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
        "For more information, check out the docs at: https://weave-docs.wandb.ai/",
        repeat=False,
    )
