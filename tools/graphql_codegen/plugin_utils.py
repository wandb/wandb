"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from graphql import (
    DirectiveNode,
    GraphQLType,
    get_named_type,
    get_nullable_type,
    is_list_type,
    value_from_ast_untyped,
)
from typing_extensions import TypeGuard


def remove_module_files(root: Path, module_names: Iterable[str]) -> None:
    sys.stdout.write("\n========== Removing files we don't need ==========\n")
    for name in module_names:
        path = (root / name).with_suffix(".py")
        sys.stdout.write(f"Removing: {path!s}\n")
        path.unlink(missing_ok=True)


def apply_ruff(path: str | Path) -> None:
    path = str(path)
    sys.stdout.write(f"\n========== Reformatting: {path} ==========\n")
    subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", path], check=True)
    subprocess.run(["ruff", "format", path], check=True)


def imported_names(stmt: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the (str) names imported by this `from ... import {names}` statement."""
    return [alias.name for alias in stmt.names]


def base_class_names(class_def: ast.ClassDef) -> list[str]:
    """Return the (str) names of the base classes of this class definition."""
    return [base.id for base in class_def.bases]


def is_field_call(expr: ast.expr) -> TypeGuard[ast.Call]:
    """Return True if this expression is a `Field(...)` function call."""
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "Field"
    )


def is_redundant_class_def(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
    """Return True if this class definition is a redundant subclass definition.

    A redundant subclass will look like:
        class MyClass(ParentClass):
            pass

    Another kind of redundant subclass is one that inherits from a fragment
    type but doesn't define any meaningfully new fields, like:
        class MyClass(MyFragmentType):
            typename__: Typename[Literal["MyFragmentType"]]

    In general, we only drop redundant subclasses if they inherit from a SINGLE parent class.
    """
    return (
        is_class_def(stmt)
        and len(stmt.bases) == 1
        and len(stmt.body) == 1
        and (
            (isinstance(stmt.body[0], ast.Pass))
            or (
                stmt.bases[0].id not in {"GQLInput", "GQLResult"}
                and isinstance(ann_assign := stmt.body[0], ast.AnnAssign)
                and isinstance(ann_assign.target, ast.Name)
                and ann_assign.target.id == "typename__"
            )
        )
    )


def is_class_def(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
    """Return True if this node is a class definition."""
    return isinstance(stmt, ast.ClassDef)


def is_import_from(stmt: ast.stmt) -> TypeGuard[ast.ImportFrom]:
    """Return True if this node is a `from ... import ...` statement."""
    return isinstance(stmt, ast.ImportFrom)


def make_model_rebuild(class_name: str) -> ast.Expr:
    """Generate the AST node for a `PydanticModel.model_rebuild()` statement."""
    return ast.Expr(
        ast.Call(
            ast.Attribute(ast.Name(class_name), "model_rebuild"), args=[], keywords=[]
        )
    )


def make_all_assignment(names: Iterable[str]) -> ast.Assign:
    """Generate an `__all__ = [...]` statement to export the given names from __init__.py."""
    return make_assign("__all__", ast.List([ast.Constant(n) for n in names]))


def make_assign(target: str, value: ast.expr) -> ast.Assign:
    """Generate the AST node for an `{target} = {value}` assignment statement."""
    return ast.Assign(targets=[ast.Name(target)], value=value)


def make_import_from(
    module: str | None, names: str | Iterable[str], level: int = 0
) -> ast.ImportFrom:
    """Generate the AST node for a `from {module} import {names}` statement."""
    names = [names] if isinstance(names, str) else names
    return ast.ImportFrom(module, names=[ast.alias(n) for n in names], level=level)


def make_literal(*vals: Any) -> ast.Subscript:
    inner_nodes = [ast.Constant(val) for val in vals]
    inner_slice = ast.Tuple(inner_nodes) if len(inner_nodes) > 1 else inner_nodes[0]
    return ast.Subscript(ast.Name("Literal"), slice=inner_slice)


# ---------------------------------------------------------------------------
# helpers to convert GraphQL `@constraints` → pydantic Field constraints
# ---------------------------------------------------------------------------


def get_constraints_directive(
    directives: Iterable[DirectiveNode],
) -> DirectiveNode | None:
    return next((d for d in directives if d.name.value == "constraints"), None)


def constraint_kwargs(
    gql_type: GraphQLType, directives: Iterable[DirectiveNode]
) -> dict[str, Any]:
    """Translate the @constraints directive, if present, to keyword args for a pydantic `Field`.

    Explicit handling by GraphQL type:
    - List[T]: map min/max -> min_length/max_length (list length)
    - String or ID: map min/max/pattern -> min_length/max_length/pattern
    - Int, Int64, or Float: map min/max -> ge/le

    Raises:
        TypeError: if the directive is present on an unsupported/unexpected GraphQL type.
    """
    if not (directive := get_constraints_directive(directives)):
        return {}

    argmap = {
        arg.name.value: value_from_ast_untyped(arg.value) for arg in directive.arguments
    }

    # Unwrap NonNull
    #   e.g. `Int! → Int`
    # However, DO NOT unwrap List, as `@constraints` can apply to fields of `List` type
    #   e.g. `tags: [TagInput!]! @constraints(max: 20)`
    gql_type = get_nullable_type(gql_type)

    if is_list_type(gql_type):
        renamed_args = {
            "min": "min_length",
            "max": "max_length",
        }
        if extra_argnames := set(argmap).difference(renamed_args):
            extra_args_repr = ", ".join(
                f"{k}: {argmap[k]!r}" for k in sorted(extra_argnames)
            )
            raise ValueError(
                f"Got unexpected `@constraints` args List-type GraphQL field: {extra_args_repr}"
            )
        return {renamed_args[k]: v for k, v in argmap.items()}

    # Otherwise handle scalar-like named types
    named = get_named_type(gql_type)
    scalar_name = named.name

    if scalar_name in {"String"}:
        renamed_args = {
            "min": "min_length",
            "max": "max_length",
            "pattern": "pattern",
        }
        if extra_argnames := set(argmap).difference(renamed_args):
            extra_args_repr = ", ".join(
                f"{k}: {argmap[k]!r}" for k in sorted(extra_argnames)
            )
            raise ValueError(
                f"Got unexpected `@constraints` args {scalar_name!r}-type GraphQL field: {extra_args_repr}"
            )
        return {renamed_args[k]: v for k, v in argmap.items()}

    if scalar_name in {"Int", "Int64", "Float"}:
        renamed_args = {
            "min": "ge",
            "max": "le",
        }
        if extra_argnames := set(argmap).difference(renamed_args):
            extra_args_repr = ", ".join(
                f"{k}: {argmap[k]!r}" for k in sorted(extra_argnames)
            )
            raise ValueError(
                f"Got unexpected `@constraints` args {scalar_name!r}-type GraphQL field: {extra_args_repr}"
            )
        return {renamed_args[k]: v for k, v in argmap.items()}

    raise TypeError(
        f"@constraints is not supported for {scalar_name!r}-type GraphQL field of node type: {gql_type!r}"
    )


def ordered_kwargs(kws: dict[str, Any]) -> list[ast.keyword]:
    ordered_argnames = (
        "min_length",
        "max_length",
        "pattern",
        "ge",
        "le",
        "min_items",
        "max_items",
    )
    return [
        ast.keyword(argname, ast.Constant(argval))
        for argname in ordered_argnames
        if (argval := kws.get(argname)) is not None
    ]


def upsert_field_call(ann_assign: ast.AnnAssign, kwargs: dict[str, Any]) -> None:
    """Ensure an ``= Field(...)`` call exists and merge in the provided kwargs.

    Preserves any existing default value/alias in the assignment.
    """
    if not kwargs:
        return

    if is_field_call(call := ann_assign.value):
        existing = {k.arg for k in call.keywords if k.arg}
        new_kwargs = [kw for kw in ordered_kwargs(kwargs) if kw.arg not in existing]
        call.keywords = [*call.keywords, *new_kwargs]
        return

    default_expr = ann_assign.value  # preserve default if present
    args = [] if (default_expr is None) else [default_expr]
    ann_assign.value = ast.Call(
        ast.Name("Field"), args=args, keywords=ordered_kwargs(kwargs)
    )
    return
