from __future__ import annotations

import inspect
import itertools
import textwrap
from collections.abc import Mapping
from typing import Callable

import wandb

from ._patch_utils import patch, unpatch

try:
    from kfp import __version__ as kfp_version
    from packaging.version import parse

    _KFP_V2 = parse(kfp_version) >= parse("2.0.0")
except (ImportError, ValueError):
    _KFP_V2 = False

# Build _wandb_logging_extras: the decorator source injected into KFP
# container scripts at compile time.  Both v1 and v2 follow the same
# pattern: an import preamble + the serialized decorator code.

_log_module = None
_import_preamble = ""
_component_factory = None

if _KFP_V2:
    try:
        from kfp.dsl import component_factory as _component_factory
    except ImportError:
        wandb.termerror(
            "kfp>=2.0.0 detected but failed to import kfp internals. "
            "Please ensure kfp is installed correctly."
        )
    else:
        from . import wandb_log_v2 as _log_module

        _import_preamble = """\
import os
import typing
from typing import Any, NamedTuple

import wandb"""
else:
    try:
        from kfp import __version__ as kfp_version
        from kfp.components import structures
        from kfp.components._components import _create_task_factory_from_component_spec
        from kfp.components._python_op import _func_to_component_spec
        from packaging.version import parse

        MIN_KFP_VERSION = "1.6.1"

        if parse(kfp_version) < parse(MIN_KFP_VERSION):
            wandb.termwarn(
                f"Your version of kfp {kfp_version} may not work.  "
                f"This integration requires kfp>={MIN_KFP_VERSION}"
            )
    except ImportError:
        wandb.termerror("kfp not found!  Please `pip install kfp`")

    try:
        from . import wandb_log_v1 as _log_module

        _import_preamble = """\
import typing
from typing import NamedTuple

import collections
from collections import namedtuple

import kfp
from kfp import components
from kfp.components import InputPath, OutputPath

import wandb"""
    except ImportError:
        pass

_decorator_code = inspect.getsource(_log_module.wandb_log) if _log_module else ""
_wandb_logging_extras = (
    f"{_import_preamble}\n\n{_decorator_code}\n" if _decorator_code else ""
)


# ---------------------------------------------------------------------------
# v1 patch functions
# ---------------------------------------------------------------------------


def _unpatch_kfp_v1() -> None:
    """Remove v1 monkey-patches from kfp.components."""
    unpatch("kfp.components")
    unpatch("kfp.components._python_op")
    unpatch("wandb.integration.kfp")


def _patch_kfp_v1() -> None:
    """Apply v1 monkey-patches to kfp.components."""
    to_patch = [
        ("kfp.components", _v1_create_component_from_func),
        ("kfp.components._python_op", _v1_create_component_from_func),
        ("kfp.components._python_op", _v1_get_function_source_definition),
        ("kfp.components._python_op", _v1_strip_type_hints),
    ]

    successes = []
    for module_name, func in to_patch:
        success = patch(module_name, func)
        successes.append(success)
    if not all(successes):
        wandb.termerror(
            "Failed to patch one or more kfp functions.  "
            "Patching @wandb_log decorator to no-op."
        )
        patch("wandb.integration.kfp", _v1_wandb_log_noop)


def _v1_wandb_log_noop(
    func: Callable | None = None,
    log_component_file: bool = True,
) -> Callable:
    """No-op fallback decorator used when v1 patching fails."""
    from functools import wraps

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def _v1_get_function_source_definition(func: Callable) -> str:
    """Get the source code of a function, preserving ``@wandb_log``.

    Modified from KFP v1. Original source:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L300-L319

    Args:
        func: The function whose source to extract.

    Returns:
        The dedented source code starting from ``@wandb_log`` or ``def``.

    Raises:
        ValueError: If the source cannot be cleaned up.
    """
    func_code = inspect.getsource(func)

    func_code = textwrap.dedent(func_code)
    func_code_lines = func_code.split("\n")

    func_code_lines = itertools.dropwhile(
        lambda x: not (x.startswith(("def", "@wandb_log"))),
        func_code_lines,
    )

    if not func_code_lines:
        raise ValueError(
            f'Failed to dedent and clean up the source of function "{func.__name__}". '
            "It is probably not properly indented."
        )

    return "\n".join(func_code_lines)


def _v1_create_component_from_func(
    func: Callable,
    output_component_file: str | None = None,
    base_image: str | None = None,
    packages_to_install: list[str] | None = None,
    annotations: Mapping[str, str] | None = None,
) -> Callable:
    """Convert a Python function to a KFP v1 component task factory.

    Modified from KFP v1. Original source:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L998-L1110

    Args:
        func: The python function to convert.
        output_component_file: Write a component definition to a local file.
        base_image: Custom Docker container image for the component.
        packages_to_install: Python packages to pip install before execution.
        annotations: Arbitrary key-value data for the component specification.

    Returns:
        A factory function with a strongly-typed signature taken from the
        python function.
    """
    core_packages = ["wandb", "kfp"]

    if not packages_to_install:
        packages_to_install = core_packages
    else:
        packages_to_install += core_packages

    component_spec = _func_to_component_spec(
        func=func,
        extra_code=_wandb_logging_extras,
        base_image=base_image,
        packages_to_install=packages_to_install,
    )
    if annotations:
        component_spec.metadata = structures.MetadataSpec(
            annotations=annotations,
        )

    if output_component_file:
        component_spec.save(output_component_file)

    return _create_task_factory_from_component_spec(component_spec)


def _v1_strip_type_hints(source_code: str) -> str:
    """No-op replacement that preserves type hints in component source.

    Modified from KFP v1. Original source:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L237-L248

    Args:
        source_code: The source code string.

    Returns:
        The source code unchanged.
    """
    return source_code


_v1_get_function_source_definition.__name__ = "_get_function_source_definition"
_v1_create_component_from_func.__name__ = "create_component_from_func"
_v1_strip_type_hints.__name__ = "strip_type_hints"


# ---------------------------------------------------------------------------
# v2 patch functions (delegated to _kfp_v2_patch module)
# ---------------------------------------------------------------------------


def _unpatch_kfp_v2() -> None:
    """Remove v2 monkey-patches from kfp.dsl.component_factory."""
    unpatch("kfp.dsl.component_factory")


def _patch_kfp_v2() -> None:
    """Apply v2 monkey-patches to kfp.dsl.component_factory."""
    if _component_factory is None:
        return

    from . import _kfp_v2_patch

    _kfp_v2_patch._orig_create = _component_factory.create_component_from_func
    _kfp_v2_patch._orig_get_cmd = (
        _component_factory._get_command_and_args_for_lightweight_component
    )
    _kfp_v2_patch._wandb_logging_extras = _wandb_logging_extras

    to_patch = [
        ("kfp.dsl.component_factory", _kfp_v2_patch.get_function_source_definition),
        ("kfp.dsl.component_factory", _kfp_v2_patch.create_component_from_func),
        (
            "kfp.dsl.component_factory",
            _kfp_v2_patch.get_command_and_args_for_lightweight_component,
        ),
    ]

    successes = []
    for module_name, func in to_patch:
        success = patch(module_name, func)
        successes.append(success)
    if not all(successes):
        wandb.termerror(
            "Failed to patch one or more kfp v2 functions. "
            "@wandb_log may not work correctly with @dsl.component."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def unpatch_kfp() -> None:
    """Undo all KFP monkey-patches applied by ``patch_kfp``."""
    if _KFP_V2:
        _unpatch_kfp_v2()
    else:
        _unpatch_kfp_v1()


def patch_kfp() -> None:
    """Apply KFP monkey-patches for the detected KFP version."""
    if _KFP_V2:
        _patch_kfp_v2()
    else:
        _patch_kfp_v1()
