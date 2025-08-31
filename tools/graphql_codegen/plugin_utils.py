"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any

import libcst as cst
import libcst.matchers as m
from ariadne_codegen.codegen import (
    generate_expr,
    generate_method_call,
    generate_pydantic_field,
)

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


def imported_names(stmt: ast.Import | ast.ImportFrom) -> set[str]:
    """Return the (str) names imported by this `from ... import {names}` statement."""
    return {alias.name for alias in stmt.names}


def base_class_names(class_def: ast.ClassDef) -> list[str]:
    """Return the (str) names of the base classes of this class definition."""
    return [base.id for base in class_def.bases]


def is_redundant_subclass_def(stmt: ast.ClassDef) -> TypeGuard[ast.ClassDef]:
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
    # if match := (
    #     m.matches(
    #         cst_stmt,
    #         m.ClassDef(
    #             bases=[m.AtMostN(m.Name(), n=1)],
    #             body=[m.Pass()],
    #         ),
    #     )
    #     | m.matches(
    #         cst_stmt,
    #         m.ClassDef(
    #             bases=[m.AllOf(m.Name(), ~(m.Name("GQLInput") | m.Name("GQLResult")))],
    #             body=[m.AnnAssign(target=m.Name("typename__"))],
    #         ),
    #     )
    # ):
    #     print(f"statement matches redundant subclass definition:\n{ast.unparse(stmt)}")
    # return match

    return (
        is_class_def(stmt)
        and len(stmt.bases) == 1
        and len(stmt.body) == 1
        and (
            (isinstance(stmt.body[0], ast.Pass))
            or (
                stmt.bases[0].id != "GQLResult"
                and isinstance(ann_assign := stmt.body[0], ast.AnnAssign)
                and isinstance(ann_assign.target, ast.Name)
                and ann_assign.target.id == "typename__"
            )
        )
    )


def is_all_assignment(stmt: ast.stmt) -> TypeGuard[ast.Assign]:
    """Return True if this node is an assignment statement to `__all__ = [...]`."""
    cst_stmt = ast_to_cst(stmt)
    return m.matches(
        cst_stmt,
        m.Assign(
            targets=[m.Name("__all__")],
            value=m.List(),
        ),
    )
    # return (
    #     isinstance(stmt, ast.Assign)
    #     and (stmt.targets[0].id == "__all__")
    #     and isinstance(stmt.value, ast.List)
    # )


def is_name(stmt: ast.stmt) -> TypeGuard[ast.Name]:
    """Return True if this node is a variable name."""
    return isinstance(stmt, ast.Name)


def is_class_def(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
    """Return True if this node is a class definition."""
    return isinstance(stmt, ast.ClassDef)


def is_import(stmt: ast.stmt) -> TypeGuard[ast.Import]:
    """Return True if this node is an `import ...` statement."""
    return isinstance(stmt, ast.Import)


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


def make_import(modules: str | Iterable[str]) -> ast.Import:
    """Generate the AST node for an `import {modules}` statement."""
    modules = [modules] if isinstance(modules, str) else modules
    return ast.Import([ast.alias(name) for name in modules])


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
    return cst.parse_statement(ast.unparse(node))
