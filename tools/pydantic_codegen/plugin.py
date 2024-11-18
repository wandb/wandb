"""Defines a custom ariadne-codegen plugin to control Python code generation from GraphQL definitions.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
import sys
import typing
from collections import deque
from contextlib import suppress
from textwrap import dedent
from typing import Any, Final, Iterable, TypeGuard, cast

from ariadne_codegen import Plugin
from ariadne_codegen.client_generators.constants import SIMPLE_TYPE_MAP
from ariadne_codegen.codegen import generate_import, generate_import_from
from graphlib import TopologicalSorter  # noqa # requires python 3.9+
from graphql import ExecutableDefinitionNode, FragmentDefinitionNode, GraphQLSchema
from pydantic import BaseModel

#: AST statement for `from .base import GQLBase, Typeame, ...`
_IMPORT_CUSTOM_TYPES: Final[ast.ImportFrom] = generate_import_from(
    from_="base", names=["GQLBase", "Typename", "Base64Id"], level=1
)
#: AST statement for `from __future__ import annotations`
_IMPORT_FUTURE_ANNOTATIONS: Final[ast.ImportFrom] = generate_import_from(
    from_="__future__", names=["annotations"]
)
#: AST statement for `import sys`
_IMPORT_SYS: Final[ast.Import] = generate_import(names=[sys.__name__])


#: Names that must be conditionally imported from `typing` or `typing_extensions` depending on python version.
COMPAT_TYPING_IMPORTS: Final[frozenset[str]] = frozenset(
    {"override", "Annotated", "Literal"}
)


class WandbCodegenPlugin(Plugin):
    """An `ariadne-codegen` plugin to customize generated Python code.

    For more info about allowed methods, see:
    - https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
    - https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
    """

    # Inherited
    schema: GraphQLSchema
    config_dict: dict[str, Any]

    #: Maps {old (redundant) class name -> replacement (base) class name}.
    class_rename_map: dict[str, Any]

    def __init__(self, schema: GraphQLSchema, config_dict: dict[str, Any]) -> None:
        super().__init__(schema, config_dict)
        self.class_rename_map = {}

        # HACK: Allow overriding the python type for the graphql `ID` type
        # For more info, see https://github.com/mirumee/ariadne-codegen/issues/316
        with suppress(LookupError):
            SIMPLE_TYPE_MAP.pop("ID")

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        module = self._cleanup_init_module(module)
        return module

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_base_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_result_types_module(
        self, module: ast.Module, operation_definition: ExecutableDefinitionNode
    ) -> ast.Module:
        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_fragments_module(
        self,
        module: ast.Module,
        fragments_definitions: dict[str, FragmentDefinitionNode],
    ) -> ast.Module:
        # Workaround: At the time of implementation, the order of:
        # - class definitions
        # - `Class.model_rebuild()` statements
        # ...in the fragments module is inconsistent.
        # See: https://github.com/mirumee/ariadne-codegen/issues/315
        module = self._ensure_class_order(module)
        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    @staticmethod
    def _ensure_class_order(module: ast.Module) -> ast.Module:
        # The generated module should have statements blocks in the following order
        # - imports
        # - class definitions
        # - GeneratedClass.model_rebuild() statements
        imports: deque[ast.Import | ast.ImportFrom] = deque()
        class_defs: deque[ast.ClassDef] = deque()
        rebuild_stmts: deque[ast.Expr] = deque()
        for stmt in module.body:
            if isinstance(stmt, (ast.ImportFrom, ast.Import)):
                imports.append(stmt)
            elif isinstance(stmt, ast.ClassDef):
                class_defs.append(stmt)
            elif isinstance(stmt, ast.Expr) and is_pydantic_model_rebuild(stmt.value):
                rebuild_stmts.append(stmt)
            else:
                raise TypeError(
                    f"Unexpected {type(stmt).__qualname__} statement in module body:\n{ast.unparse(stmt)}"
                )

        # Deterministically reorder the class definitions, ensuring parent classes are defined first
        class_order = sorted_class_names(class_defs)

        # Reorder the class definitions
        class_defs = sorted(
            class_defs,
            key=lambda nd: class_order.index(nd.name),
        )

        # Also reorder the `GeneratedModel.model_rebuild()` statements at the end
        rebuild_stmts = sorted(
            rebuild_stmts,
            key=lambda nd: class_order.index(nd.value.func.value.id),
        )

        module.body = [*imports, *class_defs, *rebuild_stmts]
        return module

    @staticmethod
    def _replace_base_classes(module: ast.Module) -> ast.Module:
        replacements = {"BaseModel": "GQLBase"}
        for stmt in module.body:
            if isinstance(stmt, ast.ClassDef):
                new_basenames = (replacements.get(nd.id) or nd.id for nd in stmt.bases)
                stmt.bases = [ast.Name(id=name) for name in new_basenames]
        return module

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        new_stmts = deque()

        for stmt in module.body:
            # Drop class definitions for redundant classes
            if isinstance(stmt, ast.ClassDef) and isinstance(stmt.body[0], ast.Pass):
                # We want to drop this ClassDef and replace references to it as well
                base: ast.Name
                [base] = stmt.bases
                self.class_rename_map[stmt.name] = base.id
            else:
                new_stmts.append(stmt)

        annotation_rewriter = FieldAnnotationRewriter(rename_map=self.class_rename_map)
        for stmt in new_stmts:
            # Statements *inside* remaining classes should consist of only field declarations (ast.AnnAssign)
            if isinstance(stmt, ast.ClassDef):
                stmt.body = [annotation_rewriter.visit(ann) for ann in stmt.body]

        module.body = list(new_stmts)

        return module

    @staticmethod
    def _fix_typing_imports(module: ast.Module) -> ast.Module:
        import_stmts: deque[ast.stmt] = deque()
        other_stmts: deque[ast.stmt] = deque()

        fix_typing_imports: set[str] = set()
        ok_typing_imports: set[str] = set()

        for stmt in module.body:
            if isinstance(stmt, ast.ImportFrom) and (stmt.module == typing.__name__):
                import_names = (alias.name for alias in stmt.names)
                for name in import_names:
                    if name in COMPAT_TYPING_IMPORTS:
                        fix_typing_imports.add(name)
                    else:
                        ok_typing_imports.add(name)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                import_stmts.append(stmt)
            else:
                other_stmts.append(stmt)

        if ok_typing_imports:
            typing_import_stmt = generate_import_from(
                names=sorted(ok_typing_imports),
                from_=typing.__name__,
            )
            import_stmts.append(typing_import_stmt)

        if fix_typing_imports:
            joined_names = ", ".join(fix_typing_imports)
            compat_import_stmt = ast.parse(
                dedent(
                    f"""\
                    if sys.version_info >= (3, 12):
                        from typing import {joined_names}
                    else:
                        from typing_extensions import {joined_names}
                    """
                )
            )
            module.body = [_IMPORT_SYS, *import_stmts, compat_import_stmt, *other_stmts]
        else:
            module.body = [*import_stmts, *other_stmts]
        return module

    def _add_common_imports(self, module: ast.Module) -> ast.Module:
        """Return a copy of the parse module after inserting common import statements."""
        # Prepend `from __future__ import annotations` to ensure postponed type hint evaluation
        module.body = [
            _IMPORT_FUTURE_ANNOTATIONS,
            _IMPORT_CUSTOM_TYPES,
            *module.body,
        ]
        return module

    def _cleanup_init_module(self, module: ast.Module) -> ast.Module:
        ignored_modules = {
            "async_base_client",
            "base_client",
            "base_model",
            "client",
            "exceptions",
        }

        removed_names: set[str] = set()
        new_stmts = deque()
        for stmt in module.body:
            if isinstance(stmt, ast.ImportFrom):
                if stmt.module in ignored_modules:
                    removed_names |= {alias.name for alias in stmt.names}
                    continue
                else:
                    new_aliases = deque()
                    for imported_alias in stmt.names:
                        if imported_alias.name in self.class_rename_map:
                            removed_names.add(imported_alias.name)
                        else:
                            new_aliases.append(imported_alias)
                    stmt.names = new_aliases

            new_stmts.append(stmt)

        for stmt in new_stmts:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                value = stmt.value
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(value, ast.List)
                ):
                    stmt.value.elts = [
                        item
                        for item in value.elts
                        if not (
                            isinstance(item, ast.Constant)
                            and (item.value in removed_names)
                        )
                    ]

        module.body = list(new_stmts)
        return module


class FieldAnnotationRewriter(ast.NodeTransformer):
    rename_map: dict[str, str]  #: Maps deleted class names -> replacement class names

    def __init__(self, rename_map: dict[str, str]):
        self.rename_map = rename_map

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        if node.target.id == "typename__":
            # Rewrite e.g.
            # - before: `typename__: Literal["MyType"] ...`
            # - after:  `typename__: Typename[Literal["MyType"]] ...`
            node.annotation = ast.Subscript(ast.Name(id="Typename"), node.annotation)
            # Drop the `= Field(...)` assignment, as this is included in `Typename`
            node.value = None

        node.annotation = self.visit(node.annotation)
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if repl := self.rename_map.get(node.id.strip("'\"")):
            node.id = repl
        return self.generic_visit(node)


# Custom helpers
def sorted_class_names(class_defs: Iterable[ast.ClassDef]) -> list[str]:
    sorter = TopologicalSorter()

    for class_def in sorted(class_defs, key=lambda cls: cls.name):
        base_names = [cast(ast.Name, base).id for base in class_def.bases]
        sorter.add(class_def.name, *base_names)

    return list(sorter.static_order())


def is_pydantic_model_rebuild(node: ast.AST) -> TypeGuard[ast.Call]:
    """Check that the given node is a generated `Model.model_rebuild()` statement (for a pydantic type)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (node.func.attr == BaseModel.model_rebuild.__name__)
    )
