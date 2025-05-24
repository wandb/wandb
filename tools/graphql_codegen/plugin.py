"""Plugin module to customize GraphQL-to-Python code generation.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from contextlib import suppress
from itertools import groupby, starmap
from pathlib import Path
from shutil import rmtree
from typing import Any, ClassVar, Iterable, Iterator

from ariadne_codegen import Plugin, contrib
from graphlib import TopologicalSorter  # noqa # Run this only with python 3.9+
from graphql import FragmentDefinitionNode, GraphQLSchema
from pydantic.alias_generators import to_camel

from .plugin_utils import (
    apply_ruff,
    base_class_names,
    collect_imported_names,
    imported_names,
    is_import_from,
    is_pydantic_field,
    is_redundant_subclass_def,
    is_union,
    make_all_assignment,
    make_annotated,
    make_import_from,
    make_literal,
    make_model_rebuild,
    make_subscript,
    remove_module_files,
)

# Class names
PYDANTIC_BASE_MODEL = "BaseModel"  #: Name of the default pydantic base class
GQL_BASE_MODEL = "GQLBase"  #: Custom base class for GraphQL types

# Names of custom field annotations
TYPENAME_ANN = "Typename"  #: Name of custom `Typename[T]` field annotation
JSON_ANN = "SerializedToJson"  #: Name of custom `SerializedToJson[T]` field annotation
GQLID_ANN = "GQLId"  #: Name of custom `GQLId` field annotation


# Names that should be imported from `typing_extensions` to ensure
# compatibility with all supported python versions.
TYPING_EXT_IMPORTS = frozenset({"override", "Annotated"})

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
        grouped_stmts.pop(ast.Expr)

        # Since we've popped all the expected statement groups, verify there's nothing left
        if grouped_stmts:
            raise ValueError(f"Unexpected statements in module: {list(grouped_stmts)}")

        # For safety, we're going to apply `.model_rebuild()` to all generated fragment types
        # This'll prevent errors that pop up in pydantic v1 like:
        #
        #   pydantic.errors.ConfigError: field "node" not yet prepared so type is still a
        #   ForwardRef, you might need to call FilesFragmentEdges.update_forward_refs().
        model_rebuilds = [make_model_rebuild(cls_def.name) for cls_def in class_defs]

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
    """A sorter for a collection of pydantic class definitions."""

    def __init__(self, class_defs: Iterable[ast.ClassDef]) -> None:
        # TopologicalSorter is used to sort the class definitions in a way that respects
        # their dependencies.
        toposorter = TopologicalSorter()

        # Note: Pre-sorting the class definitions ensures deterministic final order
        for class_def in sorted(class_defs, key=lambda cls_def: cls_def.name):
            toposorter.add(class_def.name, *base_class_names(class_def))

        # Get the deterministic, topologically sorted order of class names
        sorted_class_names = list(toposorter.static_order())

        # Build a mapping of {class name -> final sorted index}
        self.cls2idx = {name: idx for idx, name in enumerate(sorted_class_names)}

    def sort_class_defs(self, class_defs: Iterable[ast.ClassDef]) -> list[ast.ClassDef]:
        """Returns `class MyModel: ...` class definitions in topologically sorted order."""
        return sorted(class_defs, key=lambda cls_def: self.cls2idx[cls_def.name])

    def sort_model_rebuilds(self, exprs: Iterable[ast.Expr]) -> list[ast.Expr]:
        """Returns `MyModel.model_rebuild()` expressions in topologically sorted order."""
        return sorted(exprs, key=lambda expr: self.cls2idx[expr.value.func.value.id])


def forget_default_id_type() -> None:
    # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
    # See: https://github.com/mirumee/ariadne-codegen/issues/316
    from ariadne_codegen.client_generators import constants as codegen_constants

    codegen_constants.SIMPLE_TYPE_MAP.pop(ID, None)
    codegen_constants.INPUT_SCALARS_MAP.pop(ID, None)


class ExtractOperationsPlugin(contrib.extract_operations.ExtractOperationsPlugin):
    """Plugin to extract GraphQL operations from the schema.

    This is pre-defined in ariadne-codegen, we just subclass it here so it's
    picked up along with other plugins in this module.
    """


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

        # Remove any previously-generated files
        if rmtree.avoids_symlink_attacks:
            with suppress(FileNotFoundError):
                rmtree(self.package_dir)

        self.classes_to_drop = set()

        # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
        # See: https://github.com/mirumee/ariadne-codegen/issues/316
        if ID in codegen_config["scalars"]:
            forget_default_id_type()

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
        return self._rewrite_module(module)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_module(module)

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._rewrite_module(module)

    def generate_fragments_module(
        self,
        module: ast.Module,
        fragments_definitions: dict[str, FragmentDefinitionNode],
    ) -> ast.Module:
        # Maps {fragment names (i.e. python class names) -> original GraphQL type names}
        typename_map = {
            name: frag.type_condition.name.value
            for name, frag in fragments_definitions.items()
        }

        module = self._rewrite_module(module, typename_map=typename_map)
        return ast.fix_missing_locations(module)

    def _rewrite_module(
        self, module: ast.Module, typename_map: dict[str, str] | None = None
    ) -> ast.Module:
        """Apply common transformations to the generated module, excluding `__init__`."""
        self._prepend_statements(
            module,
            make_import_from("__future__", "annotations"),
            make_import_from("wandb._pydantic", [GQL_BASE_MODEL, TYPENAME_ANN]),
        )
        module = PydanticModelRewriter(typename_map).visit(module)
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
        """Import from `typing_extensions` instead of `typing` to ensure compatibility.

        Ruff will revert `typing_extensions` imports back to `typing` if appropriate later.
        """
        new_stmts = deque()
        for stmt in module.body:
            if is_import_from(imp := stmt) and (imp.module == "typing"):
                typing_imports = set(imported_names(imp)) - TYPING_EXT_IMPORTS
                split_imports = (
                    make_import_from("typing", typing_imports),
                    make_import_from("typing_extensions", TYPING_EXT_IMPORTS),
                )

                new_stmts.extend(split_imports)
            else:
                new_stmts.append(stmt)

        module.body = list(new_stmts)
        return module


class PydanticModelRewriter(ast.NodeTransformer):
    """Replaces all `pydantic.BaseModel` base classes with `GQLBase`."""

    typename_map: dict[str, str]
    """Maps {python class name -> GraphQL type name}"""

    current_class: str | None

    def __init__(self, typename_map: dict[str, str] | None = None) -> None:
        self.typename_map = typename_map or {}
        self.current_class = None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        # When descending into a class definition, temporarily store the class name
        # so we can use it to look up the GraphQL type name in `visit_AnnAssign()`.
        self.current_class = node.name
        node = self.generic_visit(node)
        self.current_class = None
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
        # Note for reference: an `AnnAssign` node is parsed from a statement like:
        #   TARGET: ANNOTATION = VALUE
        field_name: str = node.target.id

        # If a pydantic `Field(...)` is *assigned* to this attribute, keep track of its
        # kwargs so we can drop and/or move them into the annotation, as needed.

        # Check if Field(...) is on the RHS of the assignment.
        # If so, drop `default=...` from `Field(...)` and just assign the default value instead.
        # Either way, keep track of the `Field(...)` keyword args so we can move them into the type annotation.
        field_kws = {}
        if is_pydantic_field(node.value):
            field_kws = {kw.arg: kw.value for kw in node.value.keywords}

            field_default = field_kws.pop("default", None)
            node.value = None if (field_default is None) else field_default

        # If this field is `typename__`, enforce the internal `Typename` annotation
        # by wrapping the type hint like: `T -> Typename[T]`.  E.g.:
        #   BEFORE: `typename__: str = Field(alias="__typename")`
        #   AFTER:  `typename__: Typename[Literal["OrigGraphQLType"]] = "OrigGraphQLType"`
        if field_name == "typename__":
            if typename := self.typename_map.get(self.current_class):
                node.value = ast.Constant(typename)
                node.annotation = make_literal(ast.Constant(typename))

            node.annotation = make_subscript(TYPENAME_ANN, node.annotation)

            # Drop `alias="__typename"` from `Field(...)`, since it's already defined in `Typename`.
            field_kws.pop("alias", None)

        # If this is a union of a single type, drop `discriminator=...` from `Field(...)`
        # since pydantic may complain (https://github.com/pydantic/pydantic/issues/3636).
        # E.g.
        #   BEFORE: `field: Union[OnlyType,] = Field(discriminator="...")`
        #   AFTER:  `field: OnlyType`
        if is_union(outer := node.annotation) and len(inner := outer.slice.elts) == 1:
            node.annotation = inner[0]  # Union[T,] -> T
            field_kws.pop("discriminator", None)

        # If the alias is lowerCamelCase, drop `alias=...` from `Field(...)`.
        # This is already handled by `alias_generator=to_camel` in `GQLBase`.
        with suppress(LookupError, AttributeError):
            if to_camel(field_name) == field_kws["alias"].value:
                field_kws.pop("alias", None)

        # Move `Field(...)` keyword args, if any, from the assignment (right side)
        # into an `Annotated[...]` type hint (left side).
        #
        # This avoids issues in older pydantic versions when `Field(...)` is present in both
        # the annotation (left) and the assignment (right).
        #
        # E.g.:
        #   BEFORE: `field: MyType = Field(...)`
        #   AFTER:  `field: Annotated[MyType, Field(...)]`
        if field_kws:
            # Convert the remaining `Field(...)` keyword args back to an `ast.Call` node
            ast_kws = list(starmap(ast.keyword, field_kws.items()))
            field_call = ast.Call(func=ast.Name("Field"), args=[], keywords=ast_kws)

            node.annotation = make_annotated([node.annotation, field_call])

        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Visit the name of a base class in a class definition."""
        # Replace the default pydantic.BaseModel with our custom base class
        if node.id == PYDANTIC_BASE_MODEL:
            node.id = GQL_BASE_MODEL
        return self.generic_visit(node)


class RedundantClassReplacer(ast.NodeTransformer):
    """Removes redundant class definitions and references to them."""

    #: Maps {deleted class names -> replacement class names}
    replacement_names: dict[str, str]

    def __init__(self, replacement_names: dict[str, str]):
        self.replacement_names = replacement_names

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        if node.name in self.replacement_names:
            return None
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        # We need to strip quotes from `node.id`, since it may be either:
        # - `MyType` i.e. the actual type variable
        # - `"MyType"` or `'MyType'` i.e. an implicit forward ref
        unquoted_name = node.id.strip("'\"")
        if repl_name := self.replacement_names.get(unquoted_name):
            node.id = repl_name
        return self.generic_visit(node)
