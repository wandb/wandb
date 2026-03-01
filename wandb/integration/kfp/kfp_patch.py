from __future__ import annotations

import inspect
import itertools
import textwrap
from collections.abc import Mapping
from typing import Callable

import wandb

try:
    from kfp import __version__ as kfp_version
    from packaging.version import parse

    _KFP_V2 = parse(kfp_version) >= parse("2.0.0")
except Exception:
    _KFP_V2 = False

if _KFP_V2:
    try:
        from kfp.dsl import component_factory as _component_factory

        from .wandb_logging import wandb_log_v2

        _decorator_code_v2 = inspect.getsource(wandb_log_v2)
        _decorator_code_v2 = _decorator_code_v2.replace(
            "def wandb_log_v2(", "def wandb_log(", 1
        )

        _wandb_logging_extras_v2 = f"""
import os
import typing
from typing import NamedTuple

import wandb

{_decorator_code_v2}
"""
    except Exception:
        wandb.termerror(
            "kfp>=2.0.0 detected but failed to import kfp internals. "
            "Please ensure kfp is installed correctly."
        )
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

    from .wandb_logging import wandb_log

    decorator_code = inspect.getsource(wandb_log)
    wandb_logging_extras = f"""
import typing
from typing import NamedTuple

import collections
from collections import namedtuple

import kfp
from kfp import components
from kfp.components import InputPath, OutputPath

import wandb

{decorator_code}
"""


def full_path_exists(full_func):
    def get_parent_child_pairs(full_func):
        components = full_func.split(".")
        parents, children = [], []
        for i, _ in enumerate(components[:-1], 1):
            parent = ".".join(components[:i])
            child = components[i]
            parents.append(parent)
            children.append(child)
        return zip(parents, children)

    for parent, child in get_parent_child_pairs(full_func):
        module = wandb.util.get_module(parent)
        if not module or not hasattr(module, child) or getattr(module, child) is None:
            return False
    return True


def patch(module_name, func):
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


def unpatch(module_name):
    if module_name in wandb.patched:
        for module, func in wandb.patched[module_name]:
            setattr(module, func, getattr(module, f"orig_{func}"))
        wandb.patched[module_name] = []


# ---------------------------------------------------------------------------
# kfp v1 patching
# ---------------------------------------------------------------------------


def _unpatch_kfp_v1():
    unpatch("kfp.components")
    unpatch("kfp.components._python_op")
    unpatch("wandb.integration.kfp")


def _patch_kfp_v1():
    to_patch = [
        (
            "kfp.components",
            _v1_create_component_from_func,
        ),
        (
            "kfp.components._python_op",
            _v1_create_component_from_func,
        ),
        (
            "kfp.components._python_op",
            _v1_get_function_source_definition,
        ),
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
    func=None,
    # /,  # py38 only
    log_component_file=True,
):
    """Wrap a standard python function and log to W&B.

    NOTE: Because patching failed, this decorator is a no-op.
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def _v1_get_function_source_definition(func: Callable) -> str:
    """Get the source code of a function.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L300-L319.
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
):
    """Convert a Python function to a component and returns a task factory.

    The returned task factory accepts arguments and returns a task object.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L998-L1110.

    Args:
        func: The python function to convert
        base_image: Optional. Specify a custom Docker container image to use in the component. For lightweight components, the image needs to have python 3.5+. Default is the python image corresponding to the current python environment.
        output_component_file: Optional. Write a component definition to a local file. The produced component file can be loaded back by calling :code:`load_component_from_file` or :code:`load_component_from_uri`.
        packages_to_install: Optional. List of [versioned] python packages to pip install before executing the user function.
        annotations: Optional. Allows adding arbitrary key-value data to the component specification.

    Returns:
        A factory function with a strongly-typed signature taken from the python function.
        Once called with the required arguments, the factory constructs a task instance that can run the original function in a container.
    """
    core_packages = ["wandb", "kfp"]

    if not packages_to_install:
        packages_to_install = core_packages
    else:
        packages_to_install += core_packages

    component_spec = _func_to_component_spec(
        func=func,
        extra_code=wandb_logging_extras,
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
    """Strip type hints from source code.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L237-L248.
    """
    return source_code


# Alias for the patch() helper which matches by func.__name__
_v1_get_function_source_definition.__name__ = "_get_function_source_definition"
_v1_create_component_from_func.__name__ = "create_component_from_func"
_v1_strip_type_hints.__name__ = "strip_type_hints"


# ---------------------------------------------------------------------------
# kfp v2 patching
# ---------------------------------------------------------------------------


def _unpatch_kfp_v2():
    unpatch("kfp.dsl.component_factory")


def _patch_kfp_v2():
    _orig_create = _component_factory.create_component_from_func
    _orig_get_cmd = _component_factory._get_command_and_args_for_lightweight_component

    def _get_function_source_definition(func: Callable) -> str:
        """Kfp v2 patched: preserve @wandb_log decorator in serialized source."""
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

    def create_component_from_func(func, packages_to_install=None, **kwargs):
        """Kfp v2 patched: auto-add wandb to packages_to_install."""
        if getattr(func, "_wandb_logged", False):
            packages_to_install = list(packages_to_install or [])
            if not any(p.startswith("wandb") for p in packages_to_install):
                packages_to_install.append("wandb")
        return _orig_create(func, packages_to_install=packages_to_install, **kwargs)

    def _get_command_and_args_for_lightweight_component(func, **kwargs):
        """Kfp v2 patched: inject wandb decorator source into component."""
        command, args = _orig_get_cmd(func, **kwargs)

        if getattr(func, "_wandb_logged", False) and len(command) > 3:
            source = command[3]
            source = _wandb_logging_extras_v2 + "\n\n" + source
            command = list(command)
            command[3] = source

        return command, args

    to_patch = [
        ("kfp.dsl.component_factory", _get_function_source_definition),
        ("kfp.dsl.component_factory", create_component_from_func),
        (
            "kfp.dsl.component_factory",
            _get_command_and_args_for_lightweight_component,
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


def unpatch_kfp():
    if _KFP_V2:
        _unpatch_kfp_v2()
    else:
        _unpatch_kfp_v1()


def patch_kfp():
    if _KFP_V2:
        _patch_kfp_v2()
    else:
        _patch_kfp_v1()
