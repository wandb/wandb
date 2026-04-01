from __future__ import annotations

from typing import Callable

import wandb


def full_path_exists(full_func: str) -> bool:
    """Return True if every component in a dotted path exists as a module attribute.

    Args:
        full_func: A dotted path such as ``kfp.dsl.component_factory.create_component_from_func``.

    Returns:
        True if all intermediate modules and the final attribute exist.
    """
    components = full_func.split(".")
    for i in range(1, len(components)):
        parent = ".".join(components[:i])
        child = components[i]
        module = wandb.util.get_module(parent)
        if not module or not hasattr(module, child) or getattr(module, child) is None:
            return False
    return True


def patch(module_name: str, func: Callable) -> bool:
    """Monkey-patch ``func`` onto ``module_name``, keeping a backup for ``unpatch``.

    Args:
        module_name: Dotted module path (e.g. ``kfp.dsl.component_factory``).
        func: Replacement function. Its ``__name__`` must match the target
            attribute on the module.

    Returns:
        True if the patch was applied successfully.
    """
    module = wandb.util.get_module(module_name)
    success = False

    full_func = f"{module_name}.{func.__name__}"
    if not full_path_exists(full_func):
        wandb.termerror(
            f"Failed to patch {module_name}.{func.__name__}!  "
            "Please check if this package/module is installed!"
        )
    else:
        wandb.patched.setdefault(module.__name__, [])
        if [module, func.__name__] not in wandb.patched[module.__name__]:
            setattr(module, f"orig_{func.__name__}", getattr(module, func.__name__))
            setattr(module, func.__name__, func)
            wandb.patched[module.__name__].append([module, func.__name__])
        success = True

    return success


def unpatch(module_name: str) -> None:
    """Restore original functions previously replaced by ``patch``.

    Args:
        module_name: Dotted module path that was previously patched.
    """
    if module_name in wandb.patched:
        for module, func in wandb.patched[module_name]:
            setattr(module, func, getattr(module, f"orig_{func}"))
        wandb.patched[module_name] = []
