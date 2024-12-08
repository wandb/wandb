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
from textwrap import dedent, indent
from typing import Any, Final, Iterable, TypeGuard, cast

from ariadne_codegen import Plugin
from ariadne_codegen.codegen import generate_import, generate_import_from
from graphlib import TopologicalSorter  # noqa # requires python 3.9+
from graphql import ExecutableDefinitionNode, FragmentDefinitionNode, GraphQLSchema
from pydantic import BaseModel


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

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        module = self._cleanup_init_module(module)
        return module

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_base_classes(module)
        module = _fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = _fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    def generate_result_types_module(
        self, module: ast.Module, operation_definition: ExecutableDefinitionNode
    ) -> ast.Module:
        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = _fix_typing_imports(module)
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
        module = _enforce_classdef_order(module)

        module = self._replace_base_classes(module)
        module = self._replace_redundant_classes(module)
        module = _fix_typing_imports(module)
        module = self._add_common_imports(module)
        return module

    @staticmethod
    def _replace_base_classes(module: ast.Module) -> ast.Module:
        for stmt in module.body:
            if isinstance(stmt, ast.ClassDef):
                new_bases = [
                    ast.Name(id="GQLBase")
                    if (isinstance(base, ast.Name) and (base.id == "BaseModel"))
                    else base
                    for base in stmt.bases
                ]
                stmt.bases = new_bases
        return module

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        new_stmts = deque()

        for stmt in module.body:
            # Drop class definitions for redundant classes
            if (
                isinstance(stmt, ast.ClassDef)
                and len(stmt.body) == 1
                and isinstance(stmt.body[0], ast.Pass)
            ):
                # We want to drop this ClassDef and replace references to it as well
                [base_name] = [
                    base.id for base in stmt.bases if isinstance(base, ast.Name)
                ]
                self.class_rename_map[stmt.name] = base_name
            else:
                new_stmts.append(stmt)

        annotation_rewriter = FieldAnnotationRewriter(rename_map=self.class_rename_map)
        for stmt in new_stmts:
            if isinstance(stmt, ast.ClassDef):
                if stmt.name in annotation_rewriter.rename_map:
                    # Drop class definitions for redundant classes
                    continue
                else:
                    new_cls_stmts = [
                        annotation_rewriter.visit(cls_stmt)
                        if isinstance(cls_stmt, ast.AnnAssign)
                        else cls_stmt
                        for cls_stmt in stmt.body
                    ]
                    stmt.body = new_cls_stmts
            if isinstance(stmt, ast.Expr) and _is_model_rebuild_expr(stmt.value):
                # Drop `.model_rebuild()` statements for redundant classes
                continue

        module.body = list(new_stmts)

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


TYPING_IMPORTS_TO_FIX: Final[frozenset[str]] = frozenset(
    {
        "override",
        "Annotated",
        "Literal",
    }
)


class FieldAnnotationRewriter(ast.NodeTransformer):
    rename_map: dict[str, str]  #: Maps deleted class names -> replacement class names

    def __init__(self, rename_map: dict[str, str]):
        self.rename_map = rename_map

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        if node.target.id == "typename__":
            # Rewrite e.g.
            # - before: `typename__: Literal["MyType"] ...`
            # - after:  `typename__: Typename[Literal["MyType"]] ...`
            node.annotation = ast.Subscript(
                value=ast.Name(id="Typename"),
                slice=node.annotation,
            )
            # Drop the `= Field(...)` assignment, as this is included in `Typename`
            node.value = None

        node.annotation = self.visit(node.annotation)
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if repl := self.rename_map.get(node.id.strip("'\"")):
            node.id = repl
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        # In quoted annotations, e.g.
        #   x: "MyType"
        # ... "MyType" may be parsed as an ast.Constant(value='MyType') node
        if repl := self.rename_map.get(node.value.strip("'\"")):
            print(f"Replacing node: {ast.dump(node)}")
            return ast.Name(id=repl)
        return self.generic_visit(node)


# Custom helpers
def _enforce_classdef_order(module: ast.Module) -> ast.Module:
    # The generated module should have statements blocks in the following order
    # - imports
    # - class definitions
    # - GeneratedClass.model_rebuild() statements
    imports: deque[ast.Import | ast.ImportFrom] = deque()
    class_defs: deque[ast.ClassDef] = deque()
    model_rebuilds: deque[ast.Expr] = deque()
    for stmt in module.body:
        if isinstance(stmt, (ast.ImportFrom, ast.Import)):
            imports.append(stmt)
        elif isinstance(stmt, ast.ClassDef):
            class_defs.append(stmt)
        elif isinstance(stmt, ast.Expr) and _is_model_rebuild_expr(stmt.value):
            model_rebuilds.append(stmt)
        else:
            raise TypeError(
                dedent(
                    f"Unexpected {type(stmt).__qualname__} statement in module body:\n"
                    + indent(ast.unparse(stmt), prefix="  ")
                )
            )

    # Deterministically reorder the class definitions, ensuring parent classes are defined first
    sorted_class_names = _sort_class_names(class_defs)

    # Reorder the class definitions
    class_defs = sorted(
        class_defs,
        key=lambda clsdef: sorted_class_names.index(clsdef.name),
    )

    # Also reorder the `GeneratedModel.model_rebuild()` statements at the end
    model_rebuilds = sorted(
        model_rebuilds,
        key=lambda expr: sorted_class_names.index(expr.value.func.value.id),
    )

    module.body = [*imports, *class_defs, *model_rebuilds]
    return module


def _sort_class_names(class_defs: Iterable[ast.ClassDef]) -> list[str]:
    sorter = TopologicalSorter()

    for class_def in sorted(class_defs, key=lambda cls: cls.name):
        base_names = [cast(ast.Name, base).id for base in class_def.bases]
        sorter.add(class_def.name, *base_names)

    return list(sorter.static_order())


def _is_model_rebuild_expr(node: ast.AST) -> TypeGuard[ast.Call]:
    """Check that the given node is a generated `Model.model_rebuild()` statement (for a pydantic type)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (node.func.attr == BaseModel.model_rebuild.__name__)
    )


#: AST statement for `from .base import GQLBase, Typeame, ...`
_IMPORT_CUSTOM_TYPES: Final[ast.ImportFrom] = generate_import_from(
    from_="base", names=["GQLBase", "Typename", "Base64Id"], level=1
)
#: AST statement for `from __future__ import annotations`
_IMPORT_FUTURE_ANNOTATIONS: Final[ast.ImportFrom] = generate_import_from(
    from_="__future__", names=["annotations"]
)

_IMPORT_SYS: Final[ast.Import] = generate_import(names=[sys.__name__])


def _fix_typing_imports(module: ast.Module) -> ast.Module:
    import_stmts: deque[ast.stmt] = deque()
    other_stmts: deque[ast.stmt] = deque()

    imports_to_fix: set[str] = set()
    imports_to_keep: set[str] = set()

    for stmt in module.body:
        if isinstance(stmt, ast.ImportFrom) and (stmt.module == typing.__name__):
            for alias in stmt.names:
                if alias.name in TYPING_IMPORTS_TO_FIX:
                    imports_to_fix.add(alias.name)
                else:
                    imports_to_keep.add(alias.name)

                # stmt.names = list(imports_to_keep)
                # import_stmts.append(stmt)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            import_stmts.append(stmt)
        else:
            other_stmts.append(stmt)

    if imports_to_keep:
        typing_import_stmt = generate_import_from(
            names=sorted(imports_to_keep),
            from_=typing.__name__,
        )
        import_stmts.append(typing_import_stmt)

    if imports_to_fix:
        joined_imports = ", ".join(imports_to_fix)
        added_stmt = ast.parse(
            dedent(
                f"""\
                if sys.version_info >= (3, 12):
                    from typing import {joined_imports}
                else:
                    from typing_extensions import {joined_imports}
                """
            )
        )

        module.body = [_IMPORT_SYS, *import_stmts, added_stmt, *other_stmts]
    else:
        module.body = [*import_stmts, *other_stmts]
    return module
