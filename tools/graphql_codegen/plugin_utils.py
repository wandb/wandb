"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from itertools import chain
from textwrap import dedent
from typing import Any, TypeGuard

from pydantic import BaseModel, Field, field_validator


def imported_names(stmt: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the (str) names imported by this `from ... import {names}` statement."""
    return [alias.name for alias in stmt.names]


def base_class_names(class_def: ast.ClassDef) -> list[str]:
    """Return the (str) names of the base classes of this class definition."""
    return [base.id for base in class_def.bases]


def is_field_call(expr: ast.expr | None) -> TypeGuard[ast.Call]:
    """Return True if this expression is a `Field(...)` function call."""
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "Field"
    )


def is_redundant_class(stmt: ast.stmt) -> TypeGuard[ast.ClassDef]:
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


def make_lazy_init_body(import_stmts: Iterable[ast.ImportFrom]) -> list[ast.stmt]:
    """Generate the body of a package `__init__.py` that imports its submodules lazily.

    The generated GraphQL packages define hundreds of pydantic models, so importing
    everything up front makes `import wandb` noticeably slower. Instead, the imports
    are kept under `if TYPE_CHECKING:` for type checkers, and a module-level
    `__getattr__` (PEP 562) imports the submodule defining a name on first access.
    """
    import_stmts = list(import_stmts)
    names_to_export = list(chain.from_iterable(map(imported_names, import_stmts)))

    lazy_imports = ast.Dict(
        keys=[ast.Constant(name) for name in names_to_export],
        values=[
            ast.Constant("." * stmt.level + (stmt.module or ""))
            for stmt in import_stmts
            for _ in stmt.names
        ],
    )
    getattr_and_dir = ast.parse(
        dedent(
            '''
            def __getattr__(name: str) -> object:
                """Import the submodule defining `name` on first access."""
                try:
                    module_name = _LAZY_IMPORTS[name]
                except KeyError:
                    raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
                value = getattr(import_module(module_name, __name__), name)
                globals()[name] = value
                return value


            def __dir__() -> list[str]:
                return sorted({*globals(), *__all__})
            '''
        )
    ).body
    return [
        make_import_from("importlib", "import_module"),
        make_import_from("typing", "TYPE_CHECKING"),
        make_all_assignment(names_to_export),
        ast.If(test=ast.Name("TYPE_CHECKING"), body=import_stmts, orelse=[]),
        make_assign("_LAZY_IMPORTS", lazy_imports),
        *getattr_and_dir,
    ]


def make_literal(*vals: Any) -> ast.Subscript:
    inner_nodes = [ast.Constant(val) for val in vals]
    inner_slice = ast.Tuple(inner_nodes) if len(inner_nodes) > 1 else inner_nodes[0]
    return ast.Subscript(ast.Name("Literal"), slice=inner_slice)


# ---------------------------------------------------------------------------
# helpers to convert GraphQL `@constraints` → pydantic Field constraints
#
# Note that since this should only ever be executed in a dev environment,
# we're free to use Pydantic v2-only features here.
# ---------------------------------------------------------------------------
class ParsedConstraints(BaseModel, extra="ignore", populate_by_name=True):
    """Constraint values parsed from a GraphQL `@constraints` directive.

    - Field names are the arg names of the GraphQL `@constraints(...)` directive.
    - Serialization aliases are the arg names of the pydantic (V2) `Field(...)` calls.
    """

    def to_ast_keywords(self) -> list[ast.keyword]:
        """Convert the parsed constraints to Python AST `keyword` nodes."""
        pydantic_kwargs = self.model_dump(by_alias=True, exclude_none=True)
        return [
            ast.keyword(arg=name, value=ast.Constant(val))
            for name, val in pydantic_kwargs.items()
        ]


class ListConstraints(ParsedConstraints):
    min: int | None = Field(None, serialization_alias="min_length")
    max: int | None = Field(None, serialization_alias="max_length")


class StringConstraints(ParsedConstraints):
    min: int | None = Field(None, serialization_alias="min_length")
    max: int | None = Field(None, serialization_alias="max_length")
    pattern: str | None = None

    @field_validator("pattern")
    def _unescape_pattern(cls, v: str | None) -> str | None:
        """The patterns in the GraphQL schema are double-escaped, so unescape them once."""
        return v.replace(r"\\", "\\") if v else v


class NumericConstraints(ParsedConstraints):
    min: int | None = Field(None, serialization_alias="ge")
    max: int | None = Field(None, serialization_alias="le")
