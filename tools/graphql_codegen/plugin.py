"""Plugin module to customize GraphQL-to-Python code generation.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict, deque
from contextlib import suppress
from itertools import chain, groupby
from operator import attrgetter
from pathlib import Path
from shutil import rmtree
from typing import Any, ClassVar, Iterable, Iterator, Mapping

from ariadne_codegen import Plugin
from graphlib import TopologicalSorter  # Run this only with python 3.9+
from graphql import (
    ExecutableDefinitionNode,
    FragmentDefinitionNode,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLNamedType,
    GraphQLOutputType,
    GraphQLSchema,
    SelectionSetNode,
    TypeInfo,
    TypeInfoVisitor,
    TypeMetaFieldDef,
    Visitor,
    get_named_type,
    is_input_object_type,
    is_object_type,
    visit,
)
from graphql.utilities.type_info import get_field_def

from .plugin_utils import (
    apply_ruff,
    base_class_names,
    constraint_kwargs,
    imported_names,
    is_class_def,
    is_field_call,
    is_import_from,
    is_redundant_class_def,
    make_all_assignment,
    make_import_from,
    make_literal,
    make_model_rebuild,
    remove_module_files,
    upsert_field_call,
)

# Base class names
BASE_MODEL = "BaseModel"  #: Default base class name for pydantic types (to be replaced)
GQL_INPUT = "GQLInput"  #: Custom base class name for GraphQL input types
GQL_RESULT = "GQLResult"  #: Custom base class name for GraphQL result types

TYPENAME_TYPE = "Typename"  #: Custom Typename type for field annotations


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
        grouped_stmts.pop(ast.Expr)

        # Since we've popped all the expected statement groups, verify there's nothing left
        if grouped_stmts:
            raise ValueError(f"Unexpected statements in module: {list(grouped_stmts)}")

        # Deterministically reorder the class definitions/model_rebuild() statements,
        # ensuring parent classes are defined first
        sorter = ClassDefSorter(class_defs)
        class_defs = sorter.sort_class_defs(class_defs)

        # For safety, we're going to apply `.model_rebuild()` to all generated fragment types
        # This'll prevent errors that pop up in pydantic v1 like:
        #
        #   pydantic.errors.ConfigError: field "node" not yet prepared so type is still a
        #   ForwardRef, you might need to call FilesFragmentEdges.update_forward_refs().
        model_rebuilds = [make_model_rebuild(cls_def.name) for cls_def in class_defs]

        module.body = [*imports, *class_defs, *model_rebuilds]
        return module


class ClassDefSorter:
    """A sorter for a collection of class definitions."""

    def __init__(self, class_defs: Iterable[ast.ClassDef]) -> None:
        # Topologically sort the class definitions (which may depend on each other)
        # Class definitions are pre-sorted so that the final order is deterministic.
        class_dependencies = {  # Maps {class_name -> [base_class_names]}
            cls_def.name: base_class_names(cls_def)
            for cls_def in sorted(class_defs, key=attrgetter("name"))
        }

        # The deterministic, topologically sorted order of class names
        self.names = list(TopologicalSorter(class_dependencies).static_order())

    def sort_class_defs(self, class_defs: Iterable[ast.ClassDef]) -> list[ast.ClassDef]:
        """Return the class definitions in topologically sorted order."""
        return sorted(
            class_defs,
            key=lambda class_def: self.names.index(class_def.name),
        )


class GraphQLCodegenPlugin(Plugin):
    """Plugin to customize generated Python code for the `wandb` package.

    For more info about allowed methods, see:
    - https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
    - https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
    """

    # Inherited
    schema: GraphQLSchema
    config_dict: dict[str, Any]

    package_dir: Path
    """The directory where the generated modules will be added."""

    classes_to_drop: set[str]
    """Generated classes that we don't need in the final code."""

    interface2typenames: dict[str, list[str]]
    """Maps GraphQL interface type names to the concrete GraphQL object type names that implement them."""

    input_constraints: dict[tuple[str, str], dict[str, Any]]
    """Maps (InputTypeName, fieldName) -> Field(**kwargs) constraints"""

    # From ariadne-codegen, we don't currently need the generated httpx client,
    # base model, exceptions, etc., so drop these generated modules in favor of
    # the existing, internal GQL client.
    modules_to_drop: ClassVar[set[str]] = {
        "async_base_client",
        "base_client",
        "base_model",  # We'll swap in a module with our own custom base class
        "client",
        "exceptions",
    }

    def __init__(self, schema: GraphQLSchema, config_dict: dict[str, Any]) -> None:
        super().__init__(schema, config_dict)

        codegen_config: dict[str, Any] = self.config_dict["tool"]["ariadne-codegen"]

        package_path = codegen_config["target_package_path"]
        package_name = codegen_config["target_package_name"]
        self.package_dir = Path(package_path) / package_name

        self.classes_to_drop = set()
        self.interface2typenames = {}
        self.input_constraints = defaultdict(dict)

        # Remove any previously-generated files
        self._remove_target_package_dir()

        # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
        # See: https://github.com/mirumee/ariadne-codegen/issues/316
        if ID in codegen_config["scalars"]:
            from ariadne_codegen.client_generators import constants as codegen_constants

            codegen_constants.SIMPLE_TYPE_MAP.pop(ID, None)
            codegen_constants.INPUT_SCALARS_MAP.pop(ID, None)

        # Ensure standard introspection meta fields exist on `Query`.
        # `ariadne-codegen` doesn't automatically recognize meta fields
        # like `__type`, `__schema`, etc.  Inject them here so codegen can proceed.
        if query_type := self.schema.query_type:
            query_type.fields["__type"] = TypeMetaFieldDef

    def _remove_target_package_dir(self) -> None:
        """Remove the existing generated files in the target package directory, if any."""
        # Only remove existing files if `shutil.rmtree` is safe to use on the current platform.
        if not rmtree.avoids_symlink_attacks:
            sys.stdout.write(f"Skipping removal of {self.package_dir!s}\n")
            return

        with suppress(FileNotFoundError):
            sys.stdout.write(f"Removing existing files in: {self.package_dir!s}\n")
            rmtree(self.package_dir)

    def generate_init_code(self, generated_code: str) -> str:
        # This should be the last hook in the codegen process, after all modules have been generated.
        # So at this step, perform cleanup like ...
        remove_module_files(self.package_dir, self.modules_to_drop)  # Omit modules
        apply_ruff(self.package_dir)  # Apply auto-formatting
        return super().generate_init_code(generated_code)

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_init_module(module)

    def _rewrite_init_module(self, module: ast.Module) -> ast.Module:
        """Remove dropped imports and rewrite `__all__` exports in `__init__`."""
        # Drop selected import statements from the __init__ module
        kept_import_stmts = list(
            self._filter_init_imports(
                module.body,
                omit_modules=self.modules_to_drop,
                omit_names=self.classes_to_drop,
            )
        )

        # Regenerate the `__all__ = [...]` export statement
        names_to_export = chain.from_iterable(map(imported_names, kept_import_stmts))
        module.body = [
            make_all_assignment(names_to_export),
            *kept_import_stmts,
        ]
        return ast.fix_missing_locations(module)

    @staticmethod
    def _filter_init_imports(
        stmts: Iterable[ast.stmt], omit_modules: set[str], omit_names: set[str]
    ) -> Iterator[ast.ImportFrom]:
        """Yield only import statements to keep from the given module statements."""
        for stmt in stmts:
            # Keep only imports from modules that aren't being dropped
            if is_import_from(imp := stmt) and (imp.module not in omit_modules):
                # Keep only imported names that aren't being dropped
                kept_names = sorted(set(imported_names(imp)) - omit_names)
                yield make_import_from(imp.module, kept_names, level=imp.level)

    def generate_enums_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_input_class(self, class_def: ast.ClassDef, *_, **__) -> ast.ClassDef:
        # Replace the default base class: `BaseModel` -> `GQLInput`
        return ClassReplacer(rename_map={BASE_MODEL: GQL_INPUT}).visit(class_def)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        # Apply @constraints to input fields, then run generic rewrites
        self._apply_input_constraints(module)
        module = ast.fix_missing_locations(module)
        return self._rewrite_generated_module(module)

    def process_schema(self, schema: GraphQLSchema) -> GraphQLSchema:
        # Maps a GraphQL type OR interface name to the actual concrete GQL type names.
        # This is needed to accurately restrict the allowed `typename__`
        # strings on generated fragment classes.
        #
        # interface2typenames should look something like, e.g.:
        #   {
        #     "ArtifactCollection" -> ["ArtifactPortfolio", "ArtifactSequence"],
        #     "ArtifactPortfolio" -> ["ArtifactPortfolio"],
        #     "ArtifactSequence" -> ["ArtifactSequence"],
        #     ...
        #   }
        self.interface2typenames = {
            name: [impl.name for impl in schema.get_possible_types(gql_type)]
            for name, gql_type in schema.type_map.items()
        }

        # Pre-compute input constraints: (InputTypeName, fieldName) -> Field kwargs
        for type_name, gql_type in schema.type_map.items():
            if isinstance((input_type := gql_type), GraphQLInputObjectType):
                for field_name, field in input_type.fields.items():
                    if (
                        (ast_node := field.ast_node)
                        and (directives := ast_node.directives)
                        and (kws := constraint_kwargs(field.type, directives))
                    ):
                        self.input_constraints[(type_name, field_name)] = kws

        return schema

    def generate_result_class(
        self,
        class_def: ast.ClassDef,
        operation_definition: ExecutableDefinitionNode,
        selection_set: SelectionSetNode,
    ) -> ast.ClassDef:
        # Don't export this class from __init__.py (in a later step) unless:
        # - It's the the outermost result type for an operation, or
        # - It's a fragment type
        if class_def.name.lower() != operation_definition.name.value.lower():
            self.classes_to_drop.add(class_def.name)

        # Replace the default base class: `BaseModel` -> `GQLResult`
        class_def = ClassReplacer(rename_map={BASE_MODEL: GQL_RESULT}).visit(class_def)

        # Apply @constraints to result fields present in this selection set
        self._apply_result_constraints(class_def, operation_definition, selection_set)
        return class_def

    def generate_result_types_module(self, module: ast.Module, *_, **__) -> ast.Module:
        return self._rewrite_generated_module(module)

    def generate_fragments_module(
        self,
        module: ast.Module,
        fragments_definitions: dict[str, FragmentDefinitionNode],
    ) -> ast.Module:
        # Maps {fragment name -> orig GQL object type names}
        # If a fragment was defined on an interface type, `typename__` should
        # only allow the names of the interface's implemented object types.
        fragment2typenames: dict[str, list[str]] = {
            frag.name.value: (
                self.interface2typenames.get(typename := frag.type_condition.name.value)
                or [typename]
            )
            for frag in fragments_definitions.values()
        }

        # Rewrite `typename__` fields:
        #   - BEFORE: `typename__: str = Field(alias="__typename")`
        #   - AFTER:  `typename__: Literal["OrigSchemaTypeName"] = "OrigSchemaTypeName"`
        for class_def in filter(is_class_def, module.body):
            for stmt in class_def.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and (stmt.target.id == "typename__")
                    and (names := fragment2typenames.get(class_def.name))
                ):
                    stmt.annotation = make_literal(*names)
                    # Determine if we prepopulate `typename__` with a default field value
                    # - assign default: Fragment defined on a GQL object type OR interface with 1 impl.
                    # - omit default: Fragment defined on a GQL interface with multiple impls.
                    stmt.value = ast.Constant(names[0]) if len(names) == 1 else None

        return self._rewrite_generated_module(module)

    def _rewrite_generated_module(self, module: ast.Module) -> ast.Module:
        """Apply common transformations to the generated module, excluding `__init__`."""
        module = PydanticModuleRewriter().visit(module)
        module = self._replace_redundant_classes(module)
        return ast.fix_missing_locations(module)

    # ------------------------------------------------------------------
    # Constraints: helpers and appliers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_alias(ann: ast.AnnAssign) -> str | None:
        """If assignment uses Field(alias=...), return the alias string, else None."""
        if is_field_call(call := ann.value) and (
            alias_kw := next((kw for kw in call.keywords if kw.arg == "alias"), None)
        ):
            if isinstance((kw_val := alias_kw.value), ast.Constant) and isinstance(
                (alias_str := kw_val.value), str
            ):
                return alias_str
        return None

    def _apply_input_constraints(self, module: ast.Module) -> None:
        """Apply @constraints from the schema to generated input classes in this module."""
        for class_def in filter(is_class_def, module.body):
            # Look up the corresponding GraphQL input type by name
            if is_input_object_type(gql_type := self.schema.type_map[class_def.name]):
                # Map GraphQL field name -> kwargs
                type_field_kwargs: dict[str, dict[str, Any]] = {
                    field_name: self.input_constraints[(class_def.name, field_name)]
                    for field_name in gql_type.fields.keys()
                }

                # Apply to matching Python fields using alias or fallback to the Python name
                for ann in (n for n in class_def.body if isinstance(n, ast.AnnAssign)):
                    py_name = ann.target.id  # type: ignore[attr-defined]
                    gql_name = self._extract_alias(ann) or py_name
                    if kwargs := type_field_kwargs.get(gql_name):
                        upsert_field_call(ann, kwargs)

    def _apply_result_constraints(
        self,
        class_def: ast.ClassDef,
        operation_definition: ExecutableDefinitionNode,
        selection_set: SelectionSetNode,
    ) -> None:
        """Apply @constraints to fields in a generated result class based on selection set."""
        parent = self._parent_type_for_selection(operation_definition, selection_set)
        if parent is None or not is_object_type(parent):
            return

        # Collect constraints for fields present in this selection set
        field_constraints: dict[str, dict[str, Any]] = {}
        for sel in selection_set.selections:
            if getattr(sel, "kind", None) != "field":
                continue

            field_def: GraphQLField | None = get_field_def(self.schema, parent, sel)
            if not field_def or not getattr(field_def, "ast_node", None):
                continue

            if kwargs := constraint_kwargs(
                field_def.type, field_def.ast_node.directives
            ):
                field_constraints[sel.name.value] = kwargs

        if not field_constraints:
            return

        # Map alias (GraphQL name) -> AnnAssign for the generated class
        alias_to_ann: dict[str, ast.AnnAssign] = {}
        for ann in (n for n in class_def.body if isinstance(n, ast.AnnAssign)):
            alias = self._extract_alias(ann) or ann.target.id  # type: ignore[attr-defined]
            alias_to_ann[alias] = ann

        for gql_name, kwargs in field_constraints.items():
            if (ann := alias_to_ann.get(gql_name)) is not None:
                upsert_field_call(ann, kwargs)

    def _parent_type_for_selection(
        self,
        operation_definition: ExecutableDefinitionNode,
        selection_set: SelectionSetNode,
    ) -> GraphQLNamedType | GraphQLOutputType | None:
        """Derive the parent composite type for a given selection set."""
        type_info = TypeInfo(self.schema)
        locator = _ParentTypeLocator(selection_set, type_info)
        visit(operation_definition, TypeInfoVisitor(type_info, locator))
        return locator.parent_type

    @staticmethod
    def _get_classname_replacements(module: ast.Module) -> dict[str, str]:
        """Find redundant classes in the module and return a class name replacement mapping.

        Returns a replacement mapping of class names, i.e. `{redundantClass -> replacementClass}`.
        """
        return {
            class_def.name: base_class_names(class_def)[0]
            for class_def in filter(is_redundant_class_def, module.body)
        }

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        # Identify redundant classes that we can drop/replace in the code,
        rename_map = self._get_classname_replacements(module)

        # Record replaced classes for later cleanup in __init__.py
        self.classes_to_drop.update(rename_map.keys())

        # Update any references to redundant classes in the remaining class definitions
        # Replace the module body with the cleaned-up statements
        return ClassReplacer(rename_map).visit(module)


class PydanticModuleRewriter(ast.NodeTransformer):
    """Applies various modifications to a generated module with pydantic classes."""

    def visit_Module(self, node: ast.Module) -> Any:
        # Prepend shared import statements to the module. Ruff will clean this up later.
        node.body = [
            make_import_from("__future__", "annotations"),
            make_import_from("wandb._pydantic", [GQL_INPUT, GQL_RESULT, TYPENAME_TYPE]),
            make_import_from("typing_extensions", TYPING_EXTENSIONS_TYPES),
            *node.body,
        ]
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        # Drop typing imports that should be imported from `typing_extensions` instead
        if node.module == "typing":
            if kept_names := (set(imported_names(node)) - set(TYPING_EXTENSIONS_TYPES)):
                return make_import_from(node.module, kept_names)
            return None

        return node  # Otherwise, keep the import as-is

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if isinstance(node.target, ast.Name) and node.target.id == "typename__":
            # e.g. BEFORE: `typename__: Literal["MyType"] = Field(alias="__typename")`
            # e.g. AFTER:  `typename__: Typename[Literal["MyType"]]`

            # T -> Typename[T]
            node.annotation = ast.Subscript(ast.Name(TYPENAME_TYPE), node.annotation)

            # Drop `= Field(alias="__typename")`, if present
            if (
                isinstance(call := node.value, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "Field"
                and len(call.keywords) == 1
                and call.keywords[0].arg == "alias"
            ):
                node.value = None

        # If this is a union of a single type, drop the `Field(discriminator=...)`
        # since pydantic may complain.
        # See: https://github.com/pydantic/pydantic/issues/3636
        elif (
            isinstance(annotation := node.annotation, ast.Subscript)
            and isinstance(annotation.value, ast.Name)
            and annotation.value.id == "Union"
            and isinstance(annotation.slice, ast.Tuple)
            and len(annotation.slice.elts) == 1
        ):
            # e.g. BEFORE: `field: Union[OnlyType,] = Field(discriminator="...")`
            # e.g. AFTER:  `field: OnlyType`
            node.annotation = annotation.slice.elts[0]  # Union[T,] -> T
            node.value = None  # drop `= Field(discriminator=...)`, if present

        return self.generic_visit(node)


class ClassReplacer(ast.NodeTransformer):
    """Removes replaced class definitions and rewrites any references to them."""

    rename_map: dict[str, str]
    """Maps {removed_class_name -> replacement_class_name}."""

    def __init__(self, rename_map: Mapping[str, str]):
        self.rename_map = dict(rename_map)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        if node.name in self.rename_map:
            return None
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        # node.id may be the name of the hinted type, e.g. `MyType`
        # or an implicit forward ref, e.g. `"MyType"`, `'MyType'`
        unquoted_name = node.id.strip("'\"")
        with suppress(LookupError):
            node.id = self.rename_map[unquoted_name]
        return self.generic_visit(node)


class _ParentTypeLocator(Visitor):
    """Visitor that captures the parent composite type for a specific selection set."""

    def __init__(self, target: SelectionSetNode, type_info: TypeInfo) -> None:
        super().__init__()
        self._target = target
        self._type_info = type_info
        self.parent_type: GraphQLNamedType | GraphQLOutputType | None = None

    # graphql-core calls these with snake_case kinds
    def enter_selection_set(self, node: SelectionSetNode, *_: Any) -> Any:
        if node is self._target:
            # get_named_type ensures we unwrap NonNull/List wrappers
            self.parent_type = get_named_type(self._type_info.get_parent_type())
            return self.BREAK
        return None
