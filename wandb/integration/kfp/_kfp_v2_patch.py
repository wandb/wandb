"""KFP v2 monkey-patch functions for `kfp.dsl.component_factory`.

These replace three functions in the `component_factory` module so that
`@wandb_log`-decorated components automatically include W&B logging at
container runtime. Module-level state (`_orig_create`, `_orig_get_cmd`,
`_wandb_logging_extras`) is set by `kfp_patch._patch_kfp_v2` before the
patches are applied.
"""

from __future__ import annotations

import inspect
import itertools
import textwrap
from typing import Callable

_orig_create: Callable | None = None
_orig_get_cmd: Callable | None = None
_wandb_logging_extras: str = ""


def get_function_source_definition(func: Callable) -> str:
    """Preserve the `@wandb_log` decorator in serialized component source.

    KFP strips decorators when capturing a component function's source.
    This replacement keeps `@wandb_log` so the decorator is present
    when the function runs inside the container.

    Args:
        func: The component function whose source is being captured.

    Returns:
        The dedented source code, starting from the `@wandb_log` or
        `def` line.

    Raises:
        ValueError: If the source cannot be cleaned up.
    """
    func_code = inspect.getsource(func)
    func_code = textwrap.dedent(func_code)
    func_code_lines = func_code.split("\n")

    func_code_lines = itertools.dropwhile(
        lambda x: not (x.startswith("def") or x.startswith("@wandb_log")),
        func_code_lines,
    )

    if not func_code_lines:
        raise ValueError(
            f"Failed to dedent and clean up the source of function "
            f'"{func.__name__}". It is probably not properly indented.'
        )

    return "\n".join(func_code_lines)


def create_component_from_func(
    func: Callable,
    packages_to_install: list[str] | None = None,
    **kwargs: object,
) -> Callable:
    """Auto-add `wandb` to packages_to_install for logged components.

    When the component function has been decorated with `@wandb_log`,
    `wandb` is appended to the install list so it is available inside
    the container.

    Args:
        func: The component function.
        packages_to_install: Pip packages required by the component.
        **kwargs: Forwarded to the original `create_component_from_func`.

    Returns:
        The KFP component task factory.
    """
    if getattr(func, "_wandb_logged", False):
        packages_to_install = list(packages_to_install or [])
        if not any(p.startswith("wandb") for p in packages_to_install):
            packages_to_install.append("wandb")
    return _orig_create(func, packages_to_install=packages_to_install, **kwargs)


def get_command_and_args_for_lightweight_component(
    func: Callable,
    **kwargs: object,
) -> tuple:
    """Inject wandb decorator source into the component command.

    Prepends `_wandb_logging_extras` (the serialized `wandb_log`
    decorator source) to the Python script that KFP generates for the
    lightweight component.

    Args:
        func: The component function.
        **kwargs: Forwarded to the original function.

    Returns:
        A `(command, args)` tuple for the container entrypoint.
    """
    command, args = _orig_get_cmd(func, **kwargs)

    if getattr(func, "_wandb_logged", False) and len(command) > 3:
        source = command[3]
        source = _wandb_logging_extras + "\n\n" + source
        command = list(command)
        command[3] = source

    return command, args


get_function_source_definition.__name__ = "_get_function_source_definition"
get_command_and_args_for_lightweight_component.__name__ = (
    "_get_command_and_args_for_lightweight_component"
)
