"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable
from itertools import chain
from pathlib import Path
from typing import Any, TypeGuard

import libcst as cst
from ariadne_codegen.codegen import (
    generate_expr,
    generate_method_call,
    generate_pydantic_field,
)
from libcst import matchers as m


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


def imported_names(stmt: ast.Import | ast.ImportFrom) -> set[str]:
    """Return the (str) names imported by this `from ... import {names}` statement."""
    return {alias.name for alias in stmt.names}


def base_class_names(class_def: ast.ClassDef) -> list[str]:
    """Return the (str) names of the base classes of this class definition."""
    return [base.id for base in class_def.bases]


# def is_redundant_class_def(stmt: ast.ClassDef) -> TypeGuard[ast.ClassDef]:
def is_redundant_subclass_def(stmt: cst.CSTNode) -> TypeGuard[cst.ClassDef]:
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
    # if not isinstance(stmt, ast.ClassDef):
    #     return False
    # cst_stmt = ast_to_cst(stmt)

    is_empty_class_def = m.matches(
        stmt,
        m.ClassDef(
            bases=m.Name(),
            body=m.Pass(),
        ),
    )
    is_typename_only_class_def = m.matches(
        stmt,
        m.ClassDef(
            bases=m.AllOf(m.Name(), ~(m.Name("GQLInput") | m.Name("GQLResult"))),
            body=m.AnnAssign(target=m.Name("typename__")),
        ),
    )
    return is_empty_class_def | is_typename_only_class_def

    # return (
    #     is_class_def(stmt)
    #     and len(stmt.bases) == 1
    #     and len(stmt.body) == 1
    #     and (
    #         (isinstance(stmt.body[0], ast.Pass))
    #         or (
    #             stmt.bases[0].id != "GQLBase"
    #             and isinstance(ann_assign := stmt.body[0], ast.AnnAssign)
    #             and isinstance(ann_assign.target, ast.Name)
    #             and ann_assign.target.id == "typename__"
    #         )
    #     )
    # )


def is_class_def(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
    """Return True if this node is a class definition."""
    return isinstance(stmt, ast.ClassDef)


def is_import_from(stmt: ast.stmt) -> TypeGuard[ast.ImportFrom]:
    """Return True if this node is a `from ... import ...` statement."""
    return isinstance(stmt, ast.ImportFrom)


def make_model_rebuild(class_name: str) -> ast.Expr:
    """Generate the AST node for a `PydanticModel.model_rebuild()` statement."""
    return generate_expr(generate_method_call(class_name, "model_rebuild"))


def make_pydantic_field(**kwargs: Any) -> ast.Call:
    """Generate the AST node for a Pydantic `Field(...)` call."""
    kws = {
        k: v if isinstance(v, ast.expr) else ast.Constant(v) for k, v in kwargs.items()
    }
    return generate_pydantic_field(kws)


def collect_imported_names(stmts: Iterable[ast.ImportFrom]) -> list[str]:
    """Return the names to export from the __init__ module by parsing the import statements."""
    return list(chain.from_iterable(map(sorted, map(imported_names, stmts))))


def make_all_assignment(names: Iterable[str]) -> ast.Assign:
    """Generate an `__all__ = [...]` statement to export the given names from __init__.py."""
    return make_assign("__all__", ast.List([ast.Constant(name) for name in names]))


def make_assign(target: str, value: ast.expr) -> ast.Assign:
    """Generate the AST node for an `{target} = {value}` assignment statement."""
    return ast.Assign(targets=[ast.Name(target)], value=value)


def make_import_from(
    module: str, names: str | Iterable[str], level: int = 0
) -> ast.ImportFrom:
    """Generate the AST node for a `from {module} import {names}` statement."""
    names = [names] if isinstance(names, str) else names
    return ast.ImportFrom(
        module=module, names=[ast.alias(name) for name in names], level=level
    )


def make_subscript(name: str, inner: str | ast.expr) -> ast.Subscript:
    inner_node = inner if isinstance(inner, ast.expr) else ast.Constant(inner)
    return ast.Subscript(ast.Name(name), inner_node)


def ast_to_cst(node: ast.AST) -> cst.CSTNode:
    """Convert a native python AST node to a libcst CST node."""
    unparsed = ast.unparse(ast.fix_missing_locations(node)) + "\n"
    return cst.parse_statement(unparsed)


def make_literal(*vals: Any) -> ast.Subscript:
    inner_nodes = [ast.Constant(val) for val in vals]
    inner_slice = ast.Tuple(inner_nodes) if len(inner_nodes) > 1 else inner_nodes[0]
    return ast.Subscript(ast.Name("Literal"), slice=inner_slice)
