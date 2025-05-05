"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
import subprocess
import sys
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from typing import TypeGuard


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


def is_redundant_subclass_def(stmt: ast.ClassDef) -> TypeGuard[ast.ClassDef]:
    """Return True if this class definition is a redundant subclass definition.

    A redundant subclass will look like:
        class MyClass(ParentClass):
            pass

    is redundant if it has only one base class, and
    """
    return (
        is_class_def(stmt)
        and isinstance(stmt.body[0], ast.Pass)
        and len(stmt.bases) == 1
    )


def is_all_assignment(stmt: ast.stmt) -> TypeGuard[ast.Assign]:
    """Return True if this node is an assignment statement to `__all__ = [...]`."""
    return (
        isinstance(stmt, ast.Assign)
        and (stmt.targets[0].id == "__all__")
        and isinstance(stmt.value, ast.List)
    )


def is_class_def(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
    """Return True if this node is a class definition."""
    return isinstance(stmt, ast.ClassDef)


def is_import(stmt: ast.stmt) -> TypeGuard[ast.Import]:
    """Return True if this node is an `import ...` statement."""
    return isinstance(stmt, ast.Import)


def is_import_from(stmt: ast.stmt) -> TypeGuard[ast.ImportFrom]:
    """Return True if this node is a `from ... import ...` statement."""
    return isinstance(stmt, ast.ImportFrom)


def is_model_rebuild(node: ast.stmt) -> TypeGuard[ast.Expr]:
    """Return True if this node is a generated `PydanticModel.model_rebuild()` statement.

    A module-level statement like:
        MyModel.model_rebuild()

    will be an AST node like:
        Expr(
            value=Call(
                func=Attribute(
                    value=Name(id='MyModel'),
                    attr='model_rebuild',
                ), ...
            ),
        )
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and (node.value.func.attr == "model_rebuild")
    )


def make_model_rebuild(class_name: str) -> ast.Expr:
    """Generate the AST node for a `PydanticModel.model_rebuild()` statement."""
    return ast.Expr(
        value=ast.Call(
            func=ast.Attribute(attr="model_rebuild", value=ast.Name(id=class_name)),
            args=[],
            keywords=[],
        )
    )


def collect_imported_names(stmts: Iterable[ast.ImportFrom]) -> list[str]:
    """Return the names to export from the __init__ module by parsing the import statements."""
    return list(chain.from_iterable(imported_names(stmt) for stmt in stmts))


def make_all_assignment(names: Iterable[str]) -> ast.Assign:
    """Generate an `__all__ = [...]` statement to export the given names from __init__.py."""
    return make_assign(
        "__all__",
        ast.List([ast.Constant(name) for name in names]),
    )


def make_assign(target: str, value: ast.expr) -> ast.Assign:
    """Generate the AST node for an `{target} = {value}` assignment statement."""
    return ast.Assign(targets=[ast.Name(id=target)], value=value)


def make_import(modules: str | Iterable[str]) -> ast.Import:
    """Generate the AST node for an `import {modules}` statement."""
    modules = [modules] if isinstance(modules, str) else modules
    return ast.Import(names=[ast.alias(name) for name in modules])


def make_import_from(
    module: str, names: str | Iterable[str], level: int = 0
) -> ast.ImportFrom:
    """Generate the AST node for a `from {module} import {names}` statement."""
    names = [names] if isinstance(names, str) else names
    return ast.ImportFrom(
        module=module, names=[ast.alias(name) for name in names], level=level
    )
