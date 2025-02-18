from __future__ import annotations

from functools import singledispatchmethod
from typing import Optional

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic.dataclasses import dataclass as pydantic_dataclass
from wandb_graphql.language import ast

DATACLASS_CONFIG = ConfigDict(alias_generator=to_camel)


def gql_compat(query: ast.Document | str, schema_info: SchemaInfo) -> ast.Document:
    """Rewrite a GraphQL query to be compatible with the server schema.

    Args:
        query: The GraphQL query document to rewrite
        schema_info: Parsed schema info for the server

    Returns:
        Rewritten query document with only supported fields
    """
    from wandb_gql import gql

    gql_query = gql(query) if isinstance(query, str) else query
    return CompatibleGQLRewriter(schema=schema_info).rewrite(gql_query)


@pydantic_dataclass(frozen=True, config=DATACLASS_CONFIG)
class SchemaInfo:
    """Information about supported types and fields from schema introspection."""

    types: list[TypeInfo]


@pydantic_dataclass(frozen=True, config=DATACLASS_CONFIG)
class TypeInfo:
    """Information about a GraphQL type."""

    name: str
    fields: list[FieldInfo] | None = None


@pydantic_dataclass(frozen=True, config=DATACLASS_CONFIG)
class FieldInfo:
    """Information about a GraphQL field."""

    name: str
    type_: TypeRef = Field(alias="type")


@pydantic_dataclass(frozen=True, config=DATACLASS_CONFIG)
class TypeRef:
    """Information about a GraphQL type reference."""

    kind: str
    name: str | None = None
    of_type: TypeRef | None = None


@pydantic_dataclass(repr=False, config=DATACLASS_CONFIG)
class CompatibleGQLRewriter:
    """Class for rewriting GraphQL queries to be compatible with older servers."""

    #: Schema info for the server
    schema: SchemaInfo

    #: Names of supported types
    valid_types: set[str] = Field(init=False)

    #: Supported fields, as: {parent_type -> {field_name -> field_info}}
    valid_fields_by_type: dict[str, dict[str, FieldInfo]] = Field(init=False)

    #: Names of fragments that are supported by the server
    valid_fragments: set[str] = Field(default_factory=set, init=False)

    def __post_init__(self):
        self.valid_types = {typ.name for typ in self.schema.types}
        self.valid_fields_by_type = {
            typ.name: {fld.name: fld for fld in typ.fields}
            for typ in self.schema.types
            if typ.fields
        }

    def _find_valid_fragments(self, doc: ast.Document) -> None:
        """Identify fragment definitions that are defined on types supported by the server."""
        for defn in doc.definitions:
            if isinstance(defn, ast.FragmentDefinition):
                fragment_type = defn.type_condition.name.value
                if fragment_type in self.valid_types:
                    self.valid_fragments.add(defn.name.value)

    @singledispatchmethod
    def rewrite(
        self, node: Optional[ast.Node], *, parent_type: Optional[str] = None
    ) -> Optional[ast.Node]:
        """Rewrite a GraphQL node to be compatible with the server schema."""
        return node

    @rewrite.register(ast.Document)
    def _rewrite_document(
        self, node: ast.Document, *, parent_type: str | None = None
    ) -> ast.Document | None:
        # First pass: identify all invalid fragments
        self._find_valid_fragments(node)

        # Second pass: rewrite definitions
        node.definitions = [
            new_defn
            for defn in node.definitions
            if (new_defn := self.rewrite(defn, parent_type=parent_type)) is not None
        ]
        return node

    @rewrite.register(ast.FragmentDefinition)
    def _rewrite_fragment_defn(
        self, node: ast.FragmentDefinition, *, parent_type: str | None = None
    ) -> ast.FragmentDefinition | None:
        # E.g.
        #   fragment myFragment on SupportedType {
        #       __typename
        #       supportedFragmentField
        #       unsupportedFragmentField  # removed
        #   }

        # Skip fragments that weren't identified as valid earlier
        if node.name.value not in self.valid_fragments:
            return None

        parent_type = node.type_condition.name.value
        node.selection_set = self.rewrite(node.selection_set, parent_type=parent_type)
        # An empty selection set is invalid, and its parent should be removed
        return node if node.selection_set else None

    @rewrite.register(ast.OperationDefinition)
    def _rewrite_operation_defn(
        self, node: ast.OperationDefinition, *, parent_type: str | None = None
    ) -> ast.OperationDefinition | None:
        node.selection_set = self.rewrite(
            node.selection_set,
            parent_type=self._get_operation_type(node.operation),
        )
        return node

    @rewrite.register(ast.SelectionSet)
    def _rewrite_selection_set(
        self, node: ast.SelectionSet, *, parent_type: str | None = None
    ) -> ast.SelectionSet | None:
        node.selections = [
            new_sel
            for sel in node.selections
            if (new_sel := self.rewrite(sel, parent_type=parent_type)) is not None
        ]
        # An empty selection set is invalid, and its parent should be removed
        return node if node.selections else None

    @rewrite.register(ast.FragmentSpread)
    def _rewrite_fragment_spread(
        self, node: ast.FragmentSpread, *, parent_type: str | None = None
    ) -> ast.FragmentSpread | None:
        # Drop fragments that weren't identified as valid earlier
        return node if (node.name.value in self.valid_fragments) else None

    @rewrite.register(ast.Field)
    def _rewrite_field(
        self, node: ast.Field, *, parent_type: str | None = None
    ) -> ast.Field | None:
        field_name = node.name.value
        if field_name == "__typename":
            # Special handling for __typename: we'll have to make this more
            # extensible if the need arises
            field_type = "String"
        elif not (field_type := self._get_field_type(parent_type, field_name)):
            # Identify the type name for the field.  This also checks that the
            # field is supported, skipping it if not.
            return None

        # If the (valid) field doesn't have a selection set to begin with,
        # it's a leaf node, and we can return it as-is.
        if node.selection_set is None:
            return node
        else:
            node.selection_set = self.rewrite(
                node.selection_set, parent_type=field_type
            )
            # An empty selection set is invalid and should be removed
            return node if node.selection_set else None

    def _get_operation_type(self, operation: str) -> str:
        """Get the type name for a given operation name."""
        # May need to generalize this later if needed
        if operation == "mutation":
            return "Mutation"
        if operation == "query":
            return "Query"
        raise ValueError(f"Unsupported operation: {operation}")

    def _get_field_type(self, parent_type: str, field_name: str) -> str | None:
        """Return the type name for a field, given its parent type's name."""
        try:
            field_info = self.valid_fields_by_type[parent_type][field_name]
        except LookupError:
            return None

        # Unwrap NonNull and List wrappers to get the named type
        field_type = field_info.type_
        while type_ref := field_type.of_type:
            field_type = type_ref
        return field_type.name
