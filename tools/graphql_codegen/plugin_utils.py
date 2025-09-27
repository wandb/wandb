"""Custom helper functions for the GraphQL codegen plugin."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from graphql import (
    GraphQLField,
    GraphQLInputField,
    GraphQLSchema,
    get_directive_values,
    get_named_type,
    get_nullable_type,
    is_list_type,
)
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Annotated, TypeGuard


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


def is_field_call(expr: ast.expr | None) -> TypeGuard[ast.Call]:
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
class ParsedConstraints(BaseModel, extra="ignore", populate_by_name=True):
    def to_ast_keywords(self) -> list[ast.keyword]:
        """Convert the parsed constraints to python `ast.keyword` nodes."""
        return [
            ast.keyword(arg=key, value=ast.Constant(val))
            for key, val in self.model_dump(by_alias=True, exclude_none=True).items()
        ]


class ListConstraints(ParsedConstraints):
    min: Annotated[int | None, Field(alias="min_length")] = None
    max: Annotated[int | None, Field(alias="max_length")] = None


class StringConstraints(ParsedConstraints):
    min: Annotated[int | None, Field(alias="min_length")] = None
    max: Annotated[int | None, Field(alias="max_length")] = None
    pattern: str | None = None

    @field_validator("pattern")
    def _unescape_pattern(cls, v: str | None) -> str | None:
        """The patterns in the GraphQL schema are double-escaped, so unescape them once."""
        return v.replace(r"\\", "\\") if v else v


class NumericConstraints(ParsedConstraints):
    min: Annotated[int | None, Field(alias="ge")] = None
    max: Annotated[int | None, Field(alias="le")] = None


def parse_constraints(
    gql_field: GraphQLField | GraphQLInputField,
    schema: GraphQLSchema,
) -> list[ast.keyword]:
    """Translate the @constraints directive, if present, to python AST keywords for a pydantic `Field`.

    Explicit handling by GraphQL type:
    - Lists: min/max -> min_length/max_length
    - String: min/max/pattern -> min_length/max_length/pattern
    - Int, Int64, Float: min/max -> ge/le

    Raises:
        TypeError: if the directive is present on an unsupported/unexpected GraphQL type.
    """
    if not (
        (directive_defn := schema.get_directive("constraints"))
        and (field_defn := gql_field.ast_node)
        and (argmap := get_directive_values(directive_defn, field_defn))
    ):
        return []

    # Unwrap NonNull types, e.g. `Int! → Int`
    gql_type = get_nullable_type(gql_field.type)

    # However, DO NOT unwrap List, as this would miss `@constraints` on List types:
    #   e.g. `tags: [TagInput!]! @constraints(max: 20)`
    if is_list_type(gql_type):
        return ListConstraints(**argmap).to_ast_keywords()

    # Otherwise handle scalar-like named types, e.g. `String`, `Int`, `Float`
    scalar_name = get_named_type(gql_type).name
    if scalar_name in {"String"}:
        return StringConstraints(**argmap).to_ast_keywords()
    if scalar_name in {"Int", "Int64", "Float"}:
        return NumericConstraints(**argmap).to_ast_keywords()
    raise TypeError(
        f"Unable to parse @constraints for {scalar_name!r}-type GraphQL field of type: {gql_type!r}"
    )


def apply_field_constraints(
    ann: ast.AnnAssign,
    gql_field: GraphQLField | GraphQLInputField,
    schema: GraphQLSchema,
) -> ast.AnnAssign:
    """Apply any `@constraints` from the GraphQL field definition to this pydantic field.

    Should preserve any existing `Field(...)` calls, as well as any assigned default value.
    """
    if not (constraint_kws := parse_constraints(gql_field, schema)):
        return ann

    # Preserve existing `= Field(...)` calls in the annotated assignment.
    if is_field_call(pydantic_field := ann.value):
        pydantic_field.keywords = [*pydantic_field.keywords, *constraint_kws]
        return ann

    # Otherwise, if there's a default value assigned to the field, preserve it.
    if (default_expr := ann.value) is not None:
        constraint_kws = [ast.keyword("default", default_expr), *constraint_kws]

    ann.value = ast.Call(ast.Name("Field"), args=[], keywords=constraint_kws)
    return ann
