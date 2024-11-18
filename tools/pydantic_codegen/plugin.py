"""Defines a custom ariadne-codegen plugin to control Python code generation from GraphQL definitions.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
from collections import deque
from contextlib import suppress
from textwrap import dedent
from typing import Any, Final, Iterable, TypeGuard, cast

from ariadne_codegen import Plugin
from ariadne_codegen.client_generators.constants import BASE_MODEL_CLASS_NAME
from ariadne_codegen.codegen import generate_import, generate_import_from
from graphlib import TopologicalSorter  # noqa # Run this only with python 3.9+
from graphql import GraphQLSchema
from pydantic import BaseModel

DEFAULT_BASE: Final[str] = BASE_MODEL_CLASS_NAME
GQL_BASE: Final[str] = "GQLBase"
TYPENAME: Final[str] = "Typename"

#: AST statements for...
# `from __future__ import annotations`
IMPORT_ANNOTATIONS = generate_import_from(["annotations"], from_="__future__")
# `from .base import GQLBase, Typename, etc.`
IMPORT_CUSTOM_TYPES = generate_import_from([GQL_BASE, TYPENAME], from_="base", level=1)
# `import sys`
IMPORT_SYS = generate_import(["sys"])


#: Names that must be conditionally imported from `typing` or `typing_extensions` depending on python version.
TYPING_IMPORTS_TO_REWRITE: Final[tuple[str, ...]] = (
    "override",
    "Annotated",
    "Literal",
)


class FixFragmentOrder(Plugin):
    """Codegen plugin to fix inconsistent ordering of fragments module.

    HACK: At the time of implementation, the fragments module has inconsistent ordering of
    - class definitions
    - `Class.model_rebuild()` statements

    See: https://github.com/mirumee/ariadne-codegen/issues/315. This plugin is a workaround in the meantime.
    """

    def generate_fragments_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._ensure_class_order(module)

    @staticmethod
    def _ensure_class_order(module: ast.Module) -> ast.Module:
        # Separate the statements into the following expected groups:
        # - imports
        # - class definitions
        # - Model.model_rebuild() statements
        imports: deque[ast.Import | ast.ImportFrom] = deque()
        class_defs: deque[ast.ClassDef] = deque()
        model_rebuilds: deque[ast.Expr] = deque()

        for stmt in module.body:
            if is_import_stmt(stmt):
                imports.append(stmt)
            elif isinstance(stmt, ast.ClassDef):
                class_defs.append(stmt)
            elif is_model_rebuild_expr(stmt):
                model_rebuilds.append(stmt)
            else:
                stmt_type = type(stmt).__name__
                stmt_repr = ast.unparse(stmt)
                raise TypeError(f"Unexpected {stmt_type!r} statement:\n{stmt_repr}")

        # Deterministically reorder the class definitions, ensuring parent classes are defined first
        classnames = sort_classnames(class_defs)
        classname2index = {name: idx for idx, name in enumerate(classnames)}

        # Reorder the class definitions and `Model.model_rebuild()` statements
        class_defs = sorted(class_defs, key=lambda stmt: classname2index[stmt.name])
        model_rebuilds = sorted(
            model_rebuilds, key=lambda stmt: classname2index[stmt.value.func.value.id]
        )

        module.body = [*imports, *class_defs, *model_rebuilds]
        return module


def _forget_default_graphql_id_type() -> None:
    # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
    # See: https://github.com/mirumee/ariadne-codegen/issues/316
    from ariadne_codegen.client_generators import constants

    with suppress(LookupError):
        constants.SIMPLE_TYPE_MAP.pop("ID")
        constants.INPUT_SCALARS_MAP.pop("ID")


class WandbCodegenPlugin(Plugin):
    """An `ariadne-codegen` plugin to customize generated Python code.

    For more info about allowed methods, see:
    - https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
    - https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
    """

    # Inherited
    schema: GraphQLSchema
    config_dict: dict[str, Any]

    #: Names of classes that should be dropped from the generated code
    classes_to_drop: set[str]
    #: Names of generated modules that should be removed on final cleanup
    modules_to_drop: set[str]

    def __init__(self, schema: GraphQLSchema, config_dict: dict[str, Any]) -> None:
        super().__init__(schema, config_dict)
        self.classes_to_drop = set()
        self.modules_to_drop = set(
            self.config_dict["tool"]["ariadne-codegen"]["modules_to_drop"]
        )
        _forget_default_graphql_id_type()

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        return self._cleanup_init_module(module)

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_fragments_module(self, module: ast.Module, *_, **__) -> ast.Module:
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        new_stmts = deque()

        # Drop class definitions for redundant subclasses
        rename_map = {}
        for stmt in module.body:
            if is_redundant_subclass_def(stmt):
                rename_map[stmt.name] = stmt.bases[0].id
            else:
                new_stmts.append(stmt)

        # We want to replace references to redundant classes with their parent class
        field_def_rewriter = FieldDefRewriter(rename_map=rename_map)
        for stmt in new_stmts:
            if isinstance(stmt, ast.ClassDef):
                stmt.body = [field_def_rewriter.visit(ann) for ann in stmt.body]

        self.classes_to_drop |= set(rename_map)

        module.body = list(new_stmts)
        return module

    @staticmethod
    def _fix_typing_imports(module: ast.Module) -> ast.Module:
        import_stmts: deque[ast.stmt] = deque()
        other_stmts: deque[ast.stmt] = deque()

        typing_imports_to_fix: set[str] = set()
        typing_imports_to_keep: set[str] = set()

        for stmt in module.body:
            if is_typing_import_stmt(stmt):
                typing_imports = {alias.name for alias in stmt.names}

                typing_imports_to_fix |= typing_imports & {*TYPING_IMPORTS_TO_REWRITE}
                typing_imports_to_keep |= typing_imports - typing_imports_to_fix
            elif is_import_stmt(stmt):
                import_stmts.append(stmt)
            else:
                other_stmts.append(stmt)

        if typing_imports_to_keep:
            typing_import_stmt = generate_import_from(
                typing_imports_to_keep, from_="typing"
            )
            import_stmts.append(typing_import_stmt)

        if typing_imports_to_fix:
            compat_import_stmt = generate_compat_typing_import(typing_imports_to_fix)
            import_stmts = [IMPORT_SYS, *import_stmts, compat_import_stmt]

        module.body = [*import_stmts, *other_stmts]
        return module

    def _add_common_imports(self, module: ast.Module) -> ast.Module:
        """Return a copy of the parse module after inserting common import statements."""
        module.body = [
            IMPORT_ANNOTATIONS,
            IMPORT_CUSTOM_TYPES,
            *module.body,
        ]
        return module

    def _cleanup_init_module(self, module: ast.Module) -> ast.Module:
        # Identify all the imported names to be removed from `__all__ = [...]`,
        # starting with names of removed classes in other modules
        names_to_drop: set[str] = set(self.classes_to_drop)
        kept_stmts = deque()
        for stmt in module.body:
            if isinstance(stmt, ast.ImportFrom) and (
                stmt.module in self.modules_to_drop
            ):
                names_to_drop |= get_imported_names(stmt)

            elif is_import_stmt(stmt):
                kept_imported_names = get_imported_names(stmt) - names_to_drop
                stmt.names = [ast.alias(name) for name in sorted(kept_imported_names)]
                kept_stmts.append(stmt)

            else:
                kept_stmts.append(stmt)

        # Filter invalid names from `__all__ = [*names]`
        for stmt in kept_stmts:
            if is_all_assignment_stmt(stmt):
                exported: list[ast.Constant] = stmt.value.elts
                stmt.value.elts = [c for c in exported if c.value not in names_to_drop]

        module.body = list(kept_stmts)
        return module


class ReplaceBaseModel(Plugin):
    """Codegen plugin to replace default base classes `pydantic.BaseModel` with `GQLBase`."""

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        return self._replace_base_models(module)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return self._replace_base_models(module)

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._replace_base_models(module)

    def generate_fragments_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._replace_base_models(module)

    @staticmethod
    def _replace_base_models(module: ast.Module) -> ast.Module:
        """Replace all `pydantic.BaseModel` base classes with `GQLBase`."""
        for stmt in module.body:
            if isinstance(stmt, ast.ClassDef) and stmt.bases:
                stmt.bases = [
                    ast.Name(id=GQL_BASE)
                    if isinstance(base, ast.Name) and (base.id == DEFAULT_BASE)
                    else base
                    for base in stmt.bases
                ]
        return module


class FieldDefRewriter(ast.NodeTransformer):
    rename_map: dict[str, str]  #: Maps deleted class names -> replacement class names

    def __init__(self, rename_map: dict[str, str]):
        self.rename_map = rename_map

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        if node.target.id == "typename__":
            # Rewrite e.g.
            # - before: `typename__: Literal["MyType"] ...`
            # - after:  `typename__: Typename[Literal["MyType"]] ...`
            node.annotation = ast.Subscript(ast.Name(id=TYPENAME), node.annotation)
            # Drop the `= Field(...)` assignment, as this is included in `Typename`
            node.value = None

        node.annotation = self.visit(node.annotation)
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if repl := self.rename_map.get(node.id.strip("'\"")):
            node.id = repl
        return self.generic_visit(node)


# Custom helpers
def sort_classnames(class_defs: Iterable[ast.ClassDef]) -> list[str]:
    """Return a list of deterministically-ordered class names, accounting for dependencies between their definitions."""
    sorter = TopologicalSorter()

    for class_def in sorted(class_defs, key=lambda cls: cls.name):
        base_names = [cast(ast.Name, base).id for base in class_def.bases]
        sorter.add(class_def.name, *base_names)

    return list(sorter.static_order())


def get_imported_names(stmt: ast.Import | ast.ImportFrom) -> set[str]:
    """Return the names imported by this `from ... import {names}` statement."""
    return {alias.name for alias in stmt.names}


def is_redundant_subclass_def(stmt: ast.ClassDef) -> TypeGuard[ast.ClassDef]:
    """Return True if this class definition is a redundant subclass definition.

    A redundant subclass will look like:
        class MyClass(ParentClass):
            pass

    is redundant if it has only one base class, and
    """
    return (
        isinstance(stmt, ast.ClassDef)
        and isinstance(stmt.body[0], ast.Pass)
        and len(stmt.bases) == 1
    )


def is_all_assignment_stmt(stmt: ast.stmt) -> TypeGuard[ast.Assign]:
    """Return True if this node is an assignment statement to `__all__ = [...]`."""
    return (
        isinstance(stmt, ast.Assign)
        and (stmt.targets[0].id == "__all__")
        and isinstance(stmt.value, ast.List)
    )


def is_import_stmt(stmt: ast.stmt) -> TypeGuard[ast.Import | ast.ImportFrom]:
    """Return True if this node is an `import ...` or `from ... import ...` statement."""
    return isinstance(stmt, (ast.Import, ast.ImportFrom))


def is_typing_import_stmt(stmt: ast.stmt) -> TypeGuard[ast.ImportFrom]:
    """Return True if this node is a `from typing import ...` statement."""
    return isinstance(stmt, ast.ImportFrom) and (stmt.module == "typing")


def is_model_rebuild_expr(node: ast.stmt) -> TypeGuard[ast.Expr]:
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
        and (node.value.func.attr == BaseModel.model_rebuild.__name__)
    )


def generate_compat_typing_import(names: Iterable[str]) -> ast.If:
    joined_names = ", ".join(names)
    return ast.parse(
        dedent(
            f"""\
            if sys.version_info >= (3, 12):
                from typing import {joined_names}
            else:
                from typing_extensions import {joined_names}
            """
        )
    )
