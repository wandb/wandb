"""Integration module for automatic Weave initialization with W&B.

This module provides automatic initialization of Weave when:
1. Weave is installed
2. A W&B run is active with a project
3. Either:
   - Weave is already imported when wandb.init() is called (immediate init)
   - Weave is imported after wandb.init() (deferred init on first op call)
"""

import builtins
import functools
import sys
import threading
from typing import Any, Callable, Optional

from wandb import termlog, termwarn

_weave_initialized = False
_weave_init_lock = threading.Lock()
_wandb_project: Optional[str] = None
_original_weave_op: Optional[Callable] = None
_import_hook_installed = False


def _weave_import_hook(name, globals=None, locals=None, fromlist=(), level=0):
    """Import hook to set up Weave integration when it's imported."""
    # Call the original __import__
    module = _original_import(name, globals, locals, fromlist, level)

    # If this is weave being imported and we have a project, set up integration
    if name == "weave" and _wandb_project and not _weave_initialized:
        _setup_weave_wrapper(module)

    return module


# Store the original __import__
_original_import = builtins.__import__


def setup_weave_integration(project: Optional[str]) -> None:
    """Set up automatic Weave initialization for the current W&B run.

    Args:
        project: The W&B project name to use for Weave initialization.
    """
    global _wandb_project, _import_hook_installed

    # Store the project name for later use
    _wandb_project = project

    # Only proceed if project is specified
    if not project:
        return

    # Check if weave is already imported
    if "weave" in sys.modules:
        # Weave is already imported
        weave_module = sys.modules["weave"]

        # For already-imported weave with already-decorated functions,
        # we need to initialize immediately to avoid warnings
        try:
            if hasattr(weave_module, "init"):
                # Initialize Weave immediately
                weave_module.init(project)
                global _weave_initialized
                _weave_initialized = True
                termlog(f"Weave automatically initialized with project: {project}")
        except Exception as e:
            termwarn(f"Failed to automatically initialize Weave: {e}")
    else:
        # Weave is not yet imported, install import hook for lazy setup
        if not _import_hook_installed:
            builtins.__import__ = _weave_import_hook
            _import_hook_installed = True


def _setup_weave_wrapper(weave_module: Any) -> None:
    """Set up the weave.op wrapper for lazy initialization.

    This is called when weave is imported AFTER wandb.init().

    Args:
        weave_module: The imported weave module.
    """
    global _original_weave_op

    if not _original_weave_op and hasattr(weave_module, "op"):
        _original_weave_op = weave_module.op

        # Replace weave.op with our lazy-init wrapper
        weave_module.op = _create_lazy_op_wrapper(weave_module)


def _create_lazy_op_wrapper(weave_module: Any) -> Callable:
    """Create a wrapper for weave.op that performs lazy initialization.

    Args:
        weave_module: The imported weave module.

    Returns:
        A wrapped decorator that ensures Weave is initialized on first call.
    """

    def lazy_op_decorator(*decorator_args, **decorator_kwargs):
        """Wrapper for weave.op that ensures lazy initialization."""
        # Check if this is direct decoration (@weave.op) vs with args (@weave.op(...))
        is_direct_decoration = (
            len(decorator_args) == 1
            and callable(decorator_args[0])
            and not decorator_kwargs
        )

        if is_direct_decoration:
            # Direct decoration: @weave.op
            func = decorator_args[0]

            # Apply the original decorator NOW (at decoration time)
            original_decorated = _original_weave_op(func)

            # Wrap the decorated function to init on first call
            @functools.wraps(original_decorated)
            def wrapper(*args, **kwargs):
                _ensure_weave_initialized(weave_module)
                return original_decorated(*args, **kwargs)

            return wrapper
        else:
            # Decoration with arguments: @weave.op(...)
            # Apply the original decorator with args NOW
            original_decorator = _original_weave_op(*decorator_args, **decorator_kwargs)

            def decorator(func):
                # Apply the original decorator to get the decorated function
                original_decorated = original_decorator(func)

                # Wrap it to init on first call
                @functools.wraps(original_decorated)
                def wrapper(*args, **kwargs):
                    _ensure_weave_initialized(weave_module)
                    return original_decorated(*args, **kwargs)

                return wrapper

            return decorator

    # Copy any attributes from the original
    if hasattr(_original_weave_op, "__name__"):
        lazy_op_decorator.__name__ = _original_weave_op.__name__
    if hasattr(_original_weave_op, "__doc__"):
        lazy_op_decorator.__doc__ = _original_weave_op.__doc__

    return lazy_op_decorator


def _ensure_weave_initialized(weave_module: Any) -> None:
    """Ensure Weave is initialized with the W&B project.

    This is called on the first actual invocation of a @weave.op decorated function.

    Args:
        weave_module: The imported weave module.
    """
    global _weave_initialized

    # Use double-checked locking for thread safety
    if not _weave_initialized:
        with _weave_init_lock:
            if not _weave_initialized and _wandb_project:
                try:
                    # Initialize Weave with the W&B project
                    weave_module.init(_wandb_project)
                    _weave_initialized = True

                    # Log successful initialization
                    termlog(
                        f"Weave automatically initialized with project: {_wandb_project}"
                    )

                except Exception as e:
                    # Log warning but don't fail
                    termwarn(f"Failed to automatically initialize Weave: {e}")
                    # Mark as initialized to prevent repeated attempts
                    _weave_initialized = True


def cleanup_weave_integration() -> None:
    """Clean up the Weave integration and restore original state."""
    global \
        _weave_initialized, \
        _wandb_project, \
        _original_weave_op, \
        _import_hook_installed

    # Restore the original weave.op if it was replaced
    if _original_weave_op and "weave" in sys.modules:
        weave_module = sys.modules["weave"]
        if hasattr(weave_module, "op"):
            weave_module.op = _original_weave_op

    # Restore the original __import__ if we installed a hook
    if _import_hook_installed:
        builtins.__import__ = _original_import
        _import_hook_installed = False

    # Reset state
    _weave_initialized = False
    _wandb_project = None
    _original_weave_op = None
