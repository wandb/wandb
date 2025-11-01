"""Plugin module to customize GraphQL-to-Python code generation.

For more info, see:
- https://github.com/mirumee/ariadne-codegen/blob/main/PLUGINS.md
- https://github.com/mirumee/ariadne-codegen/blob/main/ariadne_codegen/plugins/base.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from contextlib import suppress
from itertools import chain
from pathlib import Path
from shutil import rmtree
from typing import Any, ClassVar, Iterable, Iterator, Mapping

from ariadne_codegen import Plugin
from graphql import (
    ExecutableDefinitionNode,
    FragmentDefinitionNode,
    GraphQLSchema,
    SchemaMetaFieldDef,
    SelectionSetNode,
    TypeMetaFieldDef,
)

from .plugin_utils import (
    base_class_names,
    imported_names,
    is_class_def,
    is_import_from,
    is_redundant_class,
    make_all_assignment,
    make_import_from,
    make_literal,
)

# Base class names
BASE_MODEL = "BaseModel"  #: Default base class name for pydantic types (to be replaced)
GQL_INPUT = "GQLInput"  #: Custom base class name for GraphQL input types
GQL_RESULT = "GQLResult"  #: Custom base class name for GraphQL result types

TYPENAME = "Typename"  #: Custom Typename type for field annotations


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

        # Remove any previously-generated files
        self._remove_existing_package_dir()

        # HACK: Override the default python type that ariadne-codegen uses for GraphQL's `ID` type.
        # See: https://github.com/mirumee/ariadne-codegen/issues/316
        if (id_name := "ID") in codegen_config["scalars"]:
            from ariadne_codegen.client_generators import constants

            constants.SIMPLE_TYPE_MAP.pop(id_name, None)
            constants.INPUT_SCALARS_MAP.pop(id_name, None)

    def _remove_existing_package_dir(self) -> None:
        """Remove the existing generated files in the target package directory, if any."""
        # Only remove existing files if `shutil.rmtree` is safe to use on the current platform.
        if not rmtree.avoids_symlink_attacks:
            sys.stdout.write(f"Skipping removal of {self.package_dir!s}\n")
            return

        with suppress(FileNotFoundError):
            rmtree(self.package_dir)
            sys.stdout.write(f"Removed existing files in: {self.package_dir!s}\n")

    def generate_init_code(self, generated_code: str) -> str:
        # This should be the last hook in the codegen process, after all modules have been generated.
        # So at this step, perform any final cleanup actions.
        self._remove_excluded_module_files()
        self._run_ruff()
        return super().generate_init_code(generated_code)

    def _remove_excluded_module_files(self) -> None:
        """Remove any generated module files we don't need."""
        paths = (
            self.package_dir / f"{name}.py" for name in sorted(self.modules_to_drop)
        )
        sys.stdout.write("\n========== Removing excluded modules ==========\n")
        for path in paths:
            sys.stdout.write(f"Removing: {path!s}\n")
            path.unlink(missing_ok=True)

    def _run_ruff(self) -> None:
        """Autofix and format the generated code via Ruff."""
        commands = (
            ["ruff", "check", "--fix", "--unsafe-fixes", str(self.package_dir)],
            ["ruff", "format", str(self.package_dir)],
        )
        sys.stdout.write(f"\n========== Reformatting: {self.package_dir} ==========\n")
        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                msg = f"Error running command: {cmd!r}. Captured output:\n{e.output.decode('utf-8')}"
                raise RuntimeError(msg) from e

    def generate_init_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_init_module(module)

    def _rewrite_init_module(self, module: ast.Module) -> ast.Module:
        """Remove dropped imports and rewrite `__all__` exports in `__init__`."""
        # Drop selected import statements from the __init__ module
        kept_import_stmts = list(self._filter_init_imports(module.body))

        # Regenerate the `__all__ = [...]` export statement
        names_to_export = chain.from_iterable(map(imported_names, kept_import_stmts))
        module.body = [
            make_all_assignment(names_to_export),
            *kept_import_stmts,
        ]
        return ast.fix_missing_locations(module)

    def _filter_init_imports(
        self, stmts: Iterable[ast.stmt]
    ) -> Iterator[ast.ImportFrom]:
        """Yield only import statements to keep from the given module statements."""
        omit_modules = self.modules_to_drop
        omit_names = self.classes_to_drop
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
        return ClassReplacer({BASE_MODEL: GQL_INPUT}).visit(class_def)

    def generate_inputs_module(self, module: ast.Module) -> ast.Module:
        return self._rewrite_generated_module(module)

    def process_schema(self, schema: GraphQLSchema) -> GraphQLSchema:
        # `ariadne-codegen` doesn't automatically recognize standard introspection fields
        # like `__type`, `__schema`, etc., so inject them here on `Query`.
        if schema.query_type:
            meta_fields = {
                "__type": TypeMetaFieldDef,
                "__schema": SchemaMetaFieldDef,
            }
            schema.query_type.fields.update(meta_fields)

        return schema

    def _concrete_typenames(self, gql_name: str) -> list[str] | None:
        """Returns the actual concrete GQL type names from the given GQL type name.

        Necessary to accurately constrain the allowed `typename__`
        strings on generated fragment classes.

        Necessary if the type is a union or interface. Should expect examples like:
        - `"ArtifactCollection" -> ["ArtifactPortfolio", "ArtifactSequence"]`
        - `"ArtifactSequence" -> ["ArtifactSequence"]`
        - `"NotARealType" -> None`
        """
        if not (gql_type := self.schema.get_type(gql_name)):
            return None
        if not (impl_types := self.schema.get_possible_types(gql_type)):
            # No implementations/unioned types, so assume it's already a concrete type.
            return [gql_name]
        return [impl.name for impl in impl_types]

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
        return ClassReplacer({BASE_MODEL: GQL_RESULT}).visit(class_def)

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
            name: typenames
            for name, frag in fragments_definitions.items()
            if (typenames := self._concrete_typenames(frag.type_condition.name.value))
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

    def _replace_redundant_classes(self, module: ast.Module) -> ast.Module:
        # Identify redundant classes that we can drop/replace in the code,
        # by mapping `{redundant_class_name -> replacement_class_name}`.
        rename_map = {
            class_def.name: base_class_names(class_def)[0]
            for class_def in filter(is_redundant_class, module.body)
        }

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
            make_import_from("wandb._pydantic", [GQL_INPUT, GQL_RESULT, TYPENAME]),
            *node.body,
        ]
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.module == "typing":
            # Import from `typing_extensions` instead, and let Ruff rewrite later.
            node.module = "typing_extensions"
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if isinstance(node.target, ast.Name) and node.target.id == "typename__":
            # e.g. BEFORE: `typename__: Literal["MyType"] = Field(alias="__typename")`
            # e.g. AFTER:  `typename__: Typename[Literal["MyType"]]`

            # T -> Typename[T]
            node.annotation = ast.Subscript(ast.Name(TYPENAME), node.annotation)

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
        # node.id may be either:
        # - the name of the hinted type, e.g. `MyType`
        # - an implicit forward ref, e.g. `"MyType"`, `'MyType'`
        # In the latter case, strip the quotes to get the actual name.
        if new_name := self.rename_map.get(node.id.strip("'\"")):
            node.id = new_name
        return self.generic_visit(node)
