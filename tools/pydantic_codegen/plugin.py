"""Defines a custom ariadne-codegen plugin to control Python code generation from GraphQL definitions.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
from typing import Any, Callable, Iterable, cast

from ariadne_codegen import Plugin
from ariadne_codegen.codegen import generate_import_from
from graphlib import TopologicalSorter  # noqa # requires python 3.9+
from graphql import ExecutableDefinitionNode, FragmentDefinitionNode, GraphQLSchema


class WandbCodegenPlugin(Plugin):
    """An `ariadne-codegen` plugin to customize generated Python code.

    For more info about allowed methods, see:
    - https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
    - https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
    """

    # Inherited
    schema: GraphQLSchema
    config_dict: dict[str, Any]

    def __init__(self, schema: GraphQLSchema, config_dict: dict[str, Any]) -> None:
        super().__init__(schema, config_dict)

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        return _add_common_imports(module)

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        return _add_common_imports(module)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return _add_common_imports(module)

    def generate_result_types_module(
        self, module: ast.Module, operation_definition: ExecutableDefinitionNode
    ) -> ast.Module:
        return _add_common_imports(module)

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
        module = _reorder_classdefs_and_rebuild_stmts(module)

        return _add_common_imports(module)


# Custom helpers
def _reorder_classdefs_and_rebuild_stmts(module: ast.Module) -> ast.Module:
    # The classes are defined consecutively: find the first/last ClassDef node(s)
    class_def_idxs: slice = _get_matching_slice(
        module.body,
        predicate=lambda n: isinstance(n, ast.ClassDef),
    )

    orig_class_defs: list[ast.ClassDef] = module.body[class_def_idxs]

    # Deterministically reorder the class definitions, ensuring parent classes are defined first
    class_name_sorter = TopologicalSorter()
    for class_def in sorted(orig_class_defs, key=lambda n: n.name):
        class_name = class_def.name
        base_names = [cast(ast.Name, base).id for base in class_def.bases]
        class_name_sorter.add(class_name, *base_names)

    sorted_class_names = list(class_name_sorter.static_order())

    # Reorder the class definitions
    module.body[class_def_idxs] = sorted(
        orig_class_defs,
        key=lambda n: sorted_class_names.index(n.name),
    )

    # Also reorder the `GeneratedModel.model_rebuild()` statements at the end
    rebuild_stmt_idxs: slice = _get_matching_slice(
        module.body,
        predicate=lambda n: (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and (n.value.func.attr == "model_rebuild")
        ),
    )

    orig_rebuild_stmts: list[ast.Expr] = module.body[rebuild_stmt_idxs]
    module.body[rebuild_stmt_idxs] = sorted(
        orig_rebuild_stmts,
        key=lambda n: sorted_class_names.index(n.value.func.value.id),
    )

    return module


def _get_matching_slice(
    stmts: Iterable[ast.stmt], predicate: Callable[..., bool]
) -> slice:
    """Return a slice that will index the first consecutive block of nodes matching the given type."""
    first: int | None = None
    last: int | None = None
    for idx, nd in enumerate(stmts):
        if (first is None) and predicate(nd):
            first = idx
        if (first is not None) and (last is None) and not predicate(nd):
            last = idx
            break
    return slice(first, last)


def _add_common_imports(module: ast.Module) -> ast.Module:
    """Return a copy of the parse module after inserting common import statements."""
    module.body = [
        generate_import_from(from_="__future__", names=["annotations"]),
        *module.body,
    ]
    return module
