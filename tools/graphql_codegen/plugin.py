"""Plugin module to customize GraphQL-to-Python code generation.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from collections.abc import Iterable
from contextlib import suppress
from graphlib import TopologicalSorter  # Run this only with python 3.9+
from itertools import groupby
from pathlib import Path
from typing import Any, ClassVar

from ariadne_codegen import Plugin
from ariadne_codegen.client_generators.constants import ANNOTATED, BASE_MODEL_CLASS_NAME
from ariadne_codegen.codegen import generate_ann_assign
from graphql import FragmentDefinitionNode, GraphQLSchema
from graphql.type.introspection import SchemaMetaFieldDef, TypeMetaFieldDef

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
    make_pydantic_field,
    make_subscript,
    remove_module_files,
)

# Names of custom-defined types
GQL_INPUT_CLASS_NAME = "GQLInput"  #: Custom base class for GraphQL input types
GQL_RESULT_CLASS_NAME = "GQLResult"  #: Custom base class for GraphQL result types
TYPENAME_TYPE = "Typename"  #: Custom Typename type for field annotations

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
        """Ensures the class definitions and `Class.model_rebuild()` statements are deterministically ordered."""
        # Separate the statements into the following expected groups:
        # - imports
        # - class definitions
        # - Model.model_rebuild() statements
        grouped_stmts: dict[type[ast.stmt], deque[ast.stmt]] = defaultdict(deque)
        for stmt_type, stmts in groupby(module.body, type):
            grouped_stmts[stmt_type].extend(stmts)

        # Check that we have only the expected statement types
        expected = {ast.ImportFrom, ast.ClassDef, ast.Expr}
        if (actual := set(grouped_stmts.keys())) != expected:
            extra = ", ".join(map(repr, sorted(actual - expected)))
            missing = ", ".join(map(repr, sorted(expected - actual)))
            raise ValueError(
                "Unexpected statements in fragments module. "
                + (f"Extra stmt types: {extra}. " if extra else "")
                + (f"Missing stmt types: {missing}. " if missing else "")
            )

        imports = grouped_stmts.pop(ast.ImportFrom)
        ordered_class_defs = grouped_stmts.pop(ast.ClassDef)

        # Drop the `.model_rebuild()` statements (we'll regenerate them)
        grouped_stmts.pop(ast.Expr)

        # Since we've popped all the expected statement groups, verify there's nothing left
        if grouped_stmts:
            raise ValueError(f"Unexpected statements in module: {list(grouped_stmts)}")

        # Deterministically reorder the class definitions/model_rebuild() statements,
        # ensuring parent classes are defined first.
        #
        # For safety, apply `.model_rebuild()` to all generated fragment types to prevent
        # errors in pydantic v1 like:
        #
        #   pydantic.errors.ConfigError: field "node" not yet prepared so type is still a
        #   ForwardRef, you might need to call FilesFragmentEdges.update_forward_refs().
        ordered_class_defs = self._sorted_class_defs(ordered_class_defs)
        model_rebuilds = [make_model_rebuild(cls_.name) for cls_ in ordered_class_defs]

        module.body = [*imports, *ordered_class_defs, *model_rebuilds]
        return module

    @staticmethod
    def _sorted_class_defs(class_defs: Iterable[ast.ClassDef]) -> list[ast.ClassDef]:
        """Return the class definitions in topologically sorted order."""
        # Pre-sort the class definitions to ensure deterministic final topological order
        ordered = sorted(class_defs, key=lambda c: c.name)

        # TopologicalSorter helps sort the classes while respecting parent-child dependencies.
        ts = TopologicalSorter({cl.name: base_class_names(cl) for cl in ordered})

        # Map class names to their index in the topologically ordered sequence
        name2idx = {name: idx for idx, name in enumerate(ts.static_order())}
        return sorted(ordered, key=lambda c: name2idx[c.name])


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

    # TODO: Delete when safe
    # #: A NodeTransformer to replace `pydantic.BaseModel` with `GQLInput/GQLResult`
    # _pydantic_model_rewriter: PydanticClassRewriter

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

        # Ensure standard introspection meta fields exist on `Query`.
        # `ariadne-codegen` doesn't automatically recognize meta fields
        # like `__type`, `__schema`, etc.  Inject them here so codegen can proceed.
        if query_type := self.schema.query_type:
            query_type.fields["__type"] = TypeMetaFieldDef
            query_type.fields["__schema"] = SchemaMetaFieldDef

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

    def generate_input_class(self, class_def: ast.ClassDef, *_, **__) -> ast.ClassDef:
        class_def.bases = [ast.Name(GQL_INPUT_CLASS_NAME)]
        return self._rewrite_class(class_def)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_result_class(self, class_def: ast.ClassDef, *_, **__) -> ast.ClassDef:
        # Replace the default `pydantic.BaseModel` parent class with our custom `GQLResult` parent class.
        base_names = base_class_names(class_def)
        class_def.bases = [
            ast.Name(GQL_RESULT_CLASS_NAME if (name == BASE_MODEL_CLASS_NAME) else name)
            for name in base_names
        ]
        return self._rewrite_class(class_def)

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._rewrite_generated_module(module)

    def _rewrite_class(
        self, node: ast.ClassDef, gql_typename: str | None = None
    ) -> ast.ClassDef:
        # Rewrite pydantic field definitions (ast.AnnAssign statements) as needed
        node.body = [
            self._rewrite_field(stmt, gql_typename)
            if isinstance(stmt, ast.AnnAssign)
            else stmt
            for stmt in node.body
        ]
        return node

    def _rewrite_field(
        self, node: ast.AnnAssign, gql_typename: str | None = None
    ) -> ast.AnnAssign:
        match target := node.target, annotation := node.annotation, node.value:
            # Handle fields with GraphQL `ID` types. Needed for fields like:
            #
            #   my_id: GQLId = Field(alias="myID")
            #
            # ... since GQLId is defined as `Annotated[..., Field(frozen=True, repr=False)]`.
            # Pydantic v1 will complain with an error like:
            #
            #   ValueError: cannot specify `Annotated` and value `Field`s together for 'my_id'
            #
            # Although Pydantic v2 is more intelligent about merging `Field(...)` metadata, we
            # need this workaround for v1 compatibility.
            case (
                _,
                ast.Name("GQLId"),
                ast.Call(ast.Name("Field"), _, pydantic_field_kws),
            ):
                kws = {kw.arg: kw.value for kw in pydantic_field_kws}
                pydantic_field = make_pydantic_field(**kws, frozen=True, repr=False)

                return generate_ann_assign(target, ast.Name("str"), pydantic_field)

            # Handle GraphQL `__typename` fields
            case ast.Name("typename__"), _, _ if gql_typename:
                # We have a specific GraphQL type name for this field, so ensure the field is:
                #   typename__: Typename[Literal["OrigSchemaTypeName"]] = "OrigSchemaTypeName"
                return generate_ann_assign(
                    target,
                    make_subscript("Typename", make_subscript("Literal", gql_typename)),
                    ast.Constant(gql_typename),
                )
            case (
                ast.Name("typename__"),
                ast.Subscript(ast.Name("Typename")),
                _,
            ):
                return node  # Nothing to do, already handled
            case ast.Name("typename__"), _, _:
                # Wrap annotation `T` with the `Typename[T]` annotation, which handles the field alias, e.g.:
                #   typename__: Literal["MyType", "Other"] = Field(alias="__typename")  # BEFORE
                #   typename__: Typename[Literal["MyType", "Other"]]                    # AFTER
                return generate_ann_assign(
                    target, make_subscript("Typename", annotation)
                )

            # If this is a union of a single type, drop `Field(discriminator=...)`
            # since pydantic may complain.
            # See: https://github.com/pydantic/pydantic/issues/3636
            case (
                _,
                ast.Subscript(ast.Name("Union"), ast.Tuple((only_type, *others))),
                ast.Call(ast.Name("Field")),
            ) if not others:
                # e.g. BEFORE: `field: Union[OnlyType,] = Field(discriminator="...")`
                # e.g. AFTER:  `field: OnlyType`
                return generate_ann_assign(target, only_type)

            case _:
                return node

    def generate_fragments_module(
        self,
        module: ast.Module,
        fragments_definitions: dict[str, FragmentDefinitionNode],
    ) -> ast.Module:
        # Maps {fragment names -> original schema type names}
        fragment2typename = {
            frag_name: frag.type_condition.name.value
            for frag_name, frag in fragments_definitions.items()
        }

        module.body = [
            self._rewrite_class(cls_, fragment2typename.get(cls_.name))
            if is_class_def(cls_ := stmt)
            else stmt
            for stmt in module.body
        ]

        module = self._rewrite_generated_module(module)
        return ast.fix_missing_locations(module)

    def _rewrite_generated_module(self, module: ast.Module) -> ast.Module:
        """Apply common transformations to the generated module, excluding `__init__`."""
        # Prepend shared import statements to the module
        module.body = [
            make_import_from("__future__", "annotations"),
            make_import_from(
                "wandb._pydantic",
                [
                    GQL_INPUT_CLASS_NAME,
                    GQL_RESULT_CLASS_NAME,
                    TYPENAME_TYPE,
                ],
            ),
            make_import_from("typing_extensions", [ANNOTATED]),
            *module.body,
        ]
        module = self._replace_redundant_classes(module)
        module = self._fix_typing_imports(module)
        return ast.fix_missing_locations(module)

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
        # Ignore imports from modules that are being dropped, and
        # ignore imported names that are being dropped (e.g. deleted classes).
        kept_imports = [
            make_import_from(
                module=imp.module,
                names=imported_names(imp) - self.classes_to_drop,
                level=imp.level,
            )
            for stmt in module.body
            if is_import_from(imp := stmt) and (imp.module not in self.modules_to_drop)
        ]

        # Replace the `__all__ = [...]` export statement
        export_stmt = make_all_assignment(names=collect_imported_names(kept_imports))

        # Update the module with the cleaned-up statements
        module.body = [*kept_imports, export_stmt]
        return module

    @staticmethod
    def _fix_typing_imports(module: ast.Module) -> ast.Module:
        """Fix the typing imports, if needed, in the generated module."""
        for stmt in module.body:
            if is_import_from(stmt) and (stmt.module == "typing"):
                stmt.names = [alias for alias in stmt.names if alias.name != ANNOTATED]

        return module


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
