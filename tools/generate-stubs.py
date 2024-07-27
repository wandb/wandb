import inspect
import pathlib
import re
import subprocess
from typing import (
    Any,
    Callable,
    Dict,
    ForwardRef,
    List,
    Literal,
    Optional,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from wandb.sdk.wandb_init import init
from wandb.sdk.wandb_login import login
from wandb.sdk.wandb_require import require
from wandb.sdk.wandb_run import Run, finish
from wandb.sdk.wandb_setup import setup
from wandb.sdk.wandb_sweep import agent, controller, sweep
from wandb.sdk.wandb_watch import unwatch, watch

INCLUDE_SYMBOLS = (
    init,
    setup,
    watch,
    unwatch,
    finish,
    login,
    sweep,
    controller,
    require,
    agent,
)
INCLUDE_RUN_METHODS = (
    "log",
    "save",
    "use_artifact",
    "log_artifact",
    "log_model",
    "use_model",
    "link_model",
    "define_metric",
    "mark_preempting",
)
STUB_FILE = pathlib.Path(__file__).parent.parent / "wandb" / "__init__.pyi"


def safe_get_type_hints(obj):
    try:
        return get_type_hints(obj)
    except NameError:
        # If we encounter a NameError, fall back to using the annotations directly
        return obj.__annotations__ if hasattr(obj, "__annotations__") else {}
    except Exception:
        # For any other exception, return an empty dict
        return {}


def type_to_string(typ):
    if typ is type(None):
        return "None"
    if isinstance(typ, str):
        return typ

    origin = get_origin(typ)
    args = get_args(typ)

    if origin is Union:
        types = [type_to_string(arg) for arg in args if arg is not type(None)]
        if len(types) < len(args):
            if len(types) == 1:
                return f"Optional[{types[0]}]"
            return f"Optional[Union[{', '.join(types)}]]"
        return f"Union[{', '.join(types)}]"

    elif origin is Literal:
        return f"Literal[{', '.join(repr(arg) for arg in args)}]"

    elif origin:
        arg_strings = ", ".join(type_to_string(arg) for arg in args)
        origin_name = origin.__name__
        if origin_name == "dict":
            origin_name = "Dict"
        elif origin_name == "list":
            origin_name = "List"
        return f"{origin_name}[{arg_strings}]" if arg_strings else origin_name

    elif isinstance(typ, type):
        if typ is dict:
            return "Dict"
        elif typ is list:
            return "List"
        return typ.__name__

    type_str = str(typ).replace("typing.", "")

    # Handle class objects
    if type_str.startswith("<class '") and type_str.endswith("'>"):
        return type_str.split("'")[1].split(".")[-1]

    # Handle Literal types
    type_str = re.sub(
        r"Literal\[(.*?)\]",
        lambda m: f"Literal[{', '.join(repr(x.strip()) for x in m.group(1).split(','))}]",
        type_str,
    )

    # Remove any remaining 'typing.' prefixes
    type_str = type_str.replace("typing.", "")

    # Preserve Dict and List
    type_str = type_str.replace("dict[", "Dict[")
    type_str = type_str.replace("list[", "List[")

    # Replace NoneType with None
    type_str = type_str.replace("NoneType", "None")

    return type_str


# def type_to_string(typ):
#     if typ is Any:
#         return "Any"
#     if typ is type(None):
#         return "None"
#     if isinstance(typ, str):
#         return typ
#     if isinstance(typ, ForwardRef):
#         return f"'{typ.__forward_arg__}'"

#     origin = get_origin(typ)
#     args = get_args(typ)

#     if origin is Union:
#         union_args = [type_to_string(arg) for arg in args if arg is not type(None)]
#         if len(args) != len(union_args):
#             return (
#                 f"Optional[{' | '.join(union_args)}]"
#                 if len(union_args) == 1
#                 else f"Optional[Union[{', '.join(union_args)}]]"
#             )
#         return f"Union[{', '.join(union_args)}]"

#     if origin is Literal:
#         return f"Literal[{', '.join(repr(arg) for arg in args)}]"

#     if origin:
#         type_name = origin.__name__ if hasattr(origin, "__name__") else str(origin)
#         if args:
#             arg_strings = ", ".join(type_to_string(arg) for arg in args)
#             return f"{type_name}[{arg_strings}]"
#         return type_name

#     if hasattr(typ, "__name__"):
#         return typ.__name__

#     return str(typ).replace("typing.", "")


def generate_function_stub(f: Any, func: Callable) -> None:
    signature = inspect.signature(func)
    docstring = inspect.getdoc(func)

    type_hints = safe_get_type_hints(func)
    if "return" in type_hints:
        return_annotation = type_to_string(type_hints["return"])
        del type_hints["return"]
    else:
        return_annotation = "Any"

    params = []
    for name, param in signature.parameters.items():
        annotation = type_to_string(type_hints.get(name, Any))
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            params.append(f"**{name}: {annotation}")
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            params.append(f"*{name}: {annotation}")
        elif param.default is param.empty:
            params.append(f"{name}: {annotation}")
        else:
            default = repr(param.default)
            params.append(f"{name}: {annotation} = {default}")

    param_str = ", ".join(params)

    f.write(f"def {func.__name__}({param_str}) -> {return_annotation}:\n")
    f.write(f'    """{docstring}"""\n')
    f.write("    ...\n\n")


def generate_stub():
    with open(STUB_FILE, "w") as f:
        # Write the module header with the necessary imports.
        f.write('"""Type stubs for the wandb module."""\n\n')
        f.write("# Autogenerated by tools/generate-stubs.py. Do not edit.\n\n")
        f.write("from os import PathLike\n")
        f.write(
            "from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Union\n\n"
        )
        f.write("import wandb.sdk.lib.paths\n")
        f.write("from wandb.sdk.artifacts import Artifact\n")
        f.write("from wandb.sdk.interface.interface import PolicyName\n")
        f.write("from wandb.sdk.wandb_metric import Metric\n")
        f.write("from wandb.sdk.wandb_run import Run\n")
        f.write("from wandb.sdk.wandb_settings import Settings\n")
        f.write("from wandb.sdk.wandb_setup import _WandbSetup\n\n")

        # Write the function stubs for the symbols in INCLUDE_SYMBOLS.
        for symbol in INCLUDE_SYMBOLS:
            generate_function_stub(f, symbol)

        # Write the Run class methods used in the __init__.py file.
        for name, method in inspect.getmembers(Run, predicate=inspect.isfunction):
            if name not in INCLUDE_RUN_METHODS:
                continue

            generate_function_stub(f, method)


def lint_and_format_stub() -> str:
    subprocess.run(["ruff", "format", STUB_FILE], check=True)
    subprocess.run(
        ["ruff", "check", STUB_FILE, "--fix", "--ignore", "UP007,F821,UP006,UP037"],
        check=True,
    )


if __name__ == "__main__":
    generate_stub()
    lint_and_format_stub()
