"""Plugin module to customize GraphQL-to-Python code generation.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from contextlib import suppress
from itertools import groupby
from pathlib import Path
from typing import Any, ClassVar, Iterable, Iterator

from ariadne_codegen import Plugin
from graphlib import TopologicalSorter  # noqa # Run this only with python 3.9+
from graphql import FragmentDefinitionNode, GraphQLSchema

from .plugin_utils import (
    apply_ruff,
    base_class_names,
    collect_imported_names,
    imported_names,
    is_class_def,
    is_import_from,
    is_redundant_subclass_def,
    make_all_assignment,
    make_import_from,
    make_model_rebuild,
    remove_module_files,
)

DEFAULT_BASE_MODEL_NAME = "BaseModel"  #: The name of the default pydantic base class

# Names of custom-defined types
CUSTOM_GQL_BASE_MODEL_NAME = "GQLBase"  #: Custom base class for GraphQL types
CUSTOM_BASE_MODEL_NAME = "Base"  #: Custom base class for other pydantic types
TYPENAME_TYPE = "Typename"  #: Custom Typename type for field annotations
JSON_TYPE = "SerializedToJson"  #: Custom SerializedToJson type for field annotations
GQLID_TYPE = "GQLId"  #: Custom GraphQL ID type for field annotations

CUSTOM_BASE_IMPORT_NAMES = [
    CUSTOM_BASE_MODEL_NAME,
    CUSTOM_GQL_BASE_MODEL_NAME,
    TYPENAME_TYPE,
]


# Names that should be imported from `typing_extensions` to ensure
# compatibility with all supported python versions.
TYPING_EXTENSIONS_TYPES = ("override", "Annotated")

# Misc
ID = "ID"  #: The GraphQL name of the ID type


class FixFragmentOrder(Plugin):
    """Plugin to ensure consistent ordering in the fragments module.

    HACK: At the time of implementation, the fragments module has inconsistent ordering of
    - class definitions
    - `Class.model_rebuild()` statements

    See: https://github.com/mirumee/ariadne-codegen/issues/315.
    This plugin is a workaround in the meantime.
    """

    def generate_fragments_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._ensure_class_order(module)

    @staticmethod
    def _ensure_class_order(module: ast.Module) -> ast.Module:
        # Separate the statements into the following expected groups:
        # - imports
        # - class definitions
        # - Model.model_rebuild() statements
        grouped_stmts: dict[type[ast.stmt], deque[ast.stmt]] = defaultdict(deque)
        for stmt_type, stmts in groupby(module.body, type):
            grouped_stmts[stmt_type].extend(stmts)

        imports = grouped_stmts.pop(ast.ImportFrom)
        class_defs = grouped_stmts.pop(ast.ClassDef)

        # Drop the `.model_rebuild()` statements (we'll regenerate them)
        _ = grouped_stmts.pop(ast.Expr)

        # Since we've popped all the expected statement groups, verify there's nothing left
        if grouped_stmts:
            raise ValueError(f"Unexpected statements in module: {list(grouped_stmts)}")

        # For safety, we're going to apply `.model_rebuild()` to all generated fragment types
        # This'll prevent errors that pop up in pydantic v1 like:
        #
        #   pydantic.errors.ConfigError: field "node" not yet prepared so type is still a
        #   ForwardRef, you might need to call FilesFragmentEdges.update_forward_refs().
        model_rebuilds = [
            make_model_rebuild(class_def.name) for class_def in class_defs
        ]

        # Deterministically reorder the class definitions/model_rebuild() statements,
        # ensuring parent classes are defined first
        sorter = ClassDefSorter(class_defs)
        module.body = [
            *imports,
            *sorter.sort_class_defs(class_defs),
            *sorter.sort_model_rebuilds(model_rebuilds),
        ]
        return module


class ClassDefSorter:
    """A sorter for a collection of class definitions."""

    def __init__(self, class_defs: Iterable[ast.ClassDef]) -> None:
        #: Used to topologically sort the class definitions (which may depend on each other)
        self.toposorter = TopologicalSorter()

        # Pre-sort the class definitions to ensure deterministic final topological order
        for class_def in sorted(class_defs, key=lambda cls: cls.name):
            self.toposorter.add(class_def.name, *base_class_names(class_def))

        #: The deterministic, topologically sorted order of class definitions
        self.static_order: list[str] = list(self.toposorter.static_order())

    def sort_class_defs(self, class_defs: Iterable[ast.ClassDef]) -> list[ast.ClassDef]:
        """Return the class definitions in topologically sorted order."""
        return sorted(
            class_defs,
            key=lambda class_def: self.static_order.index(class_def.name),
        )

    def sort_model_rebuilds(self, model_rebuilds: Iterable[ast.Expr]) -> list[ast.Expr]:
        """Return the model rebuild statements in topologically sorted order."""
        return sorted(
            model_rebuilds,
            key=lambda expr: self.static_order.index(expr.value.func.value.id),
        )


def forget_default_id_type() -> None:
    # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
    # See: https://github.com/mirumee/ariadne-codegen/issues/316
    from ariadne_codegen.client_generators import constants as codegen_constants

    codegen_constants.SIMPLE_TYPE_MAP.pop(ID, None)
    codegen_constants.INPUT_SCALARS_MAP.pop(ID, None)


class GraphQLCodegenPlugin(Plugin):
    """Plugin to customize generated Python code for the `wandb` package.

    For more info about allowed methods, see:
    - https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
    - https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
    """

    # Inherited
    schema: GraphQLSchema
    config_dict: dict[str, Any]

    #: The directory where the generated modules will be added
    package_dir: Path
    #: Generated classes that we don't need in the final code
    classes_to_drop: set[str]

    #: A NodeTransformer to replace `pydantic.BaseModel` with `GQLBase`
    _pydantic_model_rewriter: PydanticClassRewriter

    # From ariadne-codegen, we don't currently need the generated httpx client,
    # exceptions, etc., so drop these generated modules in favor of
    # the existing internal GQL client.
    modules_to_drop: ClassVar[frozenset[str]] = frozenset(
        {
            "async_base_client",
            "base_client",
            "base_model",  # We'll swap in a module with our own custom base class
            "client",
            "exceptions",
        }
    )

    def __init__(self, schema: GraphQLSchema, config_dict: dict[str, Any]) -> None:
        super().__init__(schema, config_dict)

        codegen_config: dict[str, Any] = config_dict["tool"]["ariadne-codegen"]

        package_path = codegen_config["target_package_path"]
        package_name = codegen_config["target_package_name"]
        self.package_dir = Path(package_path) / package_name

        self.classes_to_drop = set()

        # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
        # See: https://github.com/mirumee/ariadne-codegen/issues/316
        if ID in codegen_config["scalars"]:
            forget_default_id_type()

        self._pydantic_model_rewriter = PydanticClassRewriter()

    def generate_init_code(self, generated_code: str) -> str:
        # This should be the last hook in the codegen process, after all modules have been generated.
        # So at this step, perform cleanup like ...
        remove_module_files(self.package_dir, self.modules_to_drop)  # Omit modules
        apply_ruff(self.package_dir)  # Apply auto-formatting
        return super().generate_init_code(generated_code)

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        module = self._cleanup_init_module(module)
        return ast.fix_missing_locations(module)

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_fragments_module(
        self,
        module: ast.Module,
        fragments_definitions: dict[str, FragmentDefinitionNode],
    ) -> ast.Module:
        # Maps {fragment names -> original schema type names}
        fragment2typename = {
            f.name.value: f.type_condition.name.value
            for f in fragments_definitions.values()
        }

        # Rewrite `typename__` fields:
        #   - BEFORE: `typename__: str = Field(alias="__typename")`
        #   - AFTER:  `typename__: Literal["OrigSchemaTypeName"] = "OrigSchemaTypeName"`
        for class_def in filter(is_class_def, module.body):
            for stmt in class_def.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and (stmt.target.id == "typename__")
                    and (typename := fragment2typename.get(class_def.name))
                ):
                    stmt.annotation = ast.Subscript(
                        value=ast.Name(id="Literal"),
                        slice=ast.Constant(value=typename),
                    )
                    stmt.value = ast.Constant(value=typename)

        module = self._rewrite_generated_module(module)
        return ast.fix_missing_locations(module)

    def _rewrite_generated_module(self, module: ast.Module) -> ast.Module:
        """Apply common transformations to the generated module, excluding `__init__`."""
        self._prepend_statements(
            module,
            make_import_from("__future__", "annotations"),
            make_import_from("wandb._pydantic", CUSTOM_BASE_IMPORT_NAMES),
            make_import_from("typing_extensions", TYPING_EXTENSIONS_TYPES),
        )
        module = self._pydantic_model_rewriter.visit(module)
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        return ast.fix_missing_locations(module)

    def _prepend_statements(
        self, module: ast.Module, *stmts: Iterable[ast.stmt]
    ) -> None:
        """Modify the module in-place by prepending the given statements."""
        module.body = [*stmts, *module.body]

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        # Identify redundant classes and build replacement mapping
        redundant_class_defs = filter(is_redundant_subclass_def, module.body)

        class_name_replacements = {
            # maps names of: redundant subclass -> parent class
            class_def.name: base_class_names(class_def)[0]
            for class_def in redundant_class_defs
        }

        # Record removed classes for later cleanup
        self.classes_to_drop.update(class_name_replacements.keys())

        # Update any references to redundant classes in the remaining class definitions
        # Replace the module body with the cleaned-up statements
        return RedundantClassReplacer(class_name_replacements).visit(module)

    def _cleanup_init_module(self, module: ast.Module) -> ast.Module:
        """Remove dropped imports and rewrite `__all__` exports in `__init__`."""
        # Drop selected import statements from the __init__ module
        kept_import_stmts = list(
            self._filter_init_imports(
                module.body,
                omit_modules=self.modules_to_drop,
                omit_names=self.classes_to_drop,
            )
        )

        # Replace the `__all__ = [...]` export statement
        names_to_export = collect_imported_names(kept_import_stmts)
        export_stmt = make_all_assignment(names_to_export)

        # Update the module with the cleaned-up statements
        module.body = [*kept_import_stmts, export_stmt]
        return module

    @staticmethod
    def _filter_init_imports(
        stmts: Iterable[ast.stmt],
        omit_modules: Iterable[str],
        omit_names: Iterable[str],
    ) -> Iterator[ast.ImportFrom]:
        """Yield only import statements to keep from the given module statements."""
        import_from_stmts = (
            stmt
            for stmt in stmts
            # Ignore imports from modules that are being dropped
            if is_import_from(stmt) and (stmt.module not in omit_modules)
        )
        excluded_names = set(omit_names)
        for stmt in import_from_stmts:
            # Keep only imported names that aren't being dropped
            kept_names = sorted(set(imported_names(stmt)) - excluded_names)
            yield make_import_from(stmt.module, kept_names, level=stmt.level)

    @staticmethod
    def _fix_typing_imports(module: ast.Module) -> ast.Module:
        """Fix the typing imports, if needed, in the generated module."""
        module.body = list(_filter_and_fix_typing_imports(module.body))
        return module


def _filter_and_fix_typing_imports(stmts: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    for stmt in stmts:
        if is_import_from(stmt) and (stmt.module == "typing"):
            # Drop typing imports that must be imported from typing_extensions
            if kept_names := (set(imported_names(stmt)) - set(TYPING_EXTENSIONS_TYPES)):
                yield make_import_from(stmt.module, kept_names)
        else:
            # Keep all non-typing import statements and any other statements
            yield stmt


class PydanticClassRewriter(ast.NodeTransformer):
    """Replaces all `pydantic.BaseModel` base classes with `GQLBase`."""

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom | None:
        # Drop imports of the pydantic.BaseModel class
        # Note: import of the custom base class `GQLBase` is added elsewhere
        if node.module == "pydantic":
            node.names = [
                alias for alias in node.names if alias.name != DEFAULT_BASE_MODEL_NAME
            ]
        return node if node.names else None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        if node.target.id == "typename__":
            # e.g. BEFORE: `typename__: Literal["MyType"] = Field(alias="__typename")`
            # e.g. AFTER:  `typename__: Typename[Literal["MyType"]]`
            node.annotation = ast.Subscript(  # T -> Typename[T]
                value=ast.Name(id=TYPENAME_TYPE),
                slice=node.annotation,
            )
            # Drop `= Field(alias="__typename")`, if present
            if (
                isinstance(node.value, ast.Call)
                and node.value.func.id == "Field"
                and len(node.value.keywords) == 1
                and node.value.keywords[0].arg == "alias"
            ):
                node.value = None

        # If this is a union of a single type, drop the `Field(discriminator=...)`
        # since pydantic may complain.
        # See: https://github.com/pydantic/pydantic/issues/3636
        elif (
            isinstance(annotation := node.annotation, ast.Subscript)
            and annotation.value.id == "Union"
            and isinstance(annotation.slice, ast.Tuple)
            and len(annotation.slice.elts) == 1
        ):
            # e.g. BEFORE: `field: Union[OnlyType,] = Field(discriminator="...")`
            # e.g. AFTER:  `field: OnlyType`
            node.annotation = annotation.slice.elts[0]  # Union[T,] -> T
            node.value = None  # drop `= Field(discriminator=...)`, if present

        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Visit the name of a base class in a class definition."""
        # Replace the default pydantic.BaseModel with our custom base class
        if node.id == DEFAULT_BASE_MODEL_NAME:
            node.id = CUSTOM_GQL_BASE_MODEL_NAME
        return self.generic_visit(node)


class RedundantClassReplacer(ast.NodeTransformer):
    """Removes redundant class definitions and references to them."""

    #: Maps deleted class names -> replacement class names
    replacement_names: dict[str, str]

    def __init__(self, replacement_names: dict[str, str]):
        self.replacement_names = replacement_names

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        if node.name in self.replacement_names:
            return None
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        # node.id may be the name of the hinted type, e.g. `MyType`
        # or an implicit forward ref, e.g. `"MyType"`, `'MyType'`
        unquoted_name = node.id.strip("'\"")
        with suppress(LookupError):
            node.id = self.replacement_names[unquoted_name]
        return self.generic_visit(node)
