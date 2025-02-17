from __future__ import annotations

from functools import singledispatchmethod
from typing import Optional

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic.dataclasses import dataclass as pydantic_dataclass
from wandb_gql import gql
from wandb_graphql.language.ast import Document as GQLDocument
from wandb_graphql.language.ast import Field as GQLField
from wandb_graphql.language.ast import FragmentDefinition as GQLFragmentDefinition
from wandb_graphql.language.ast import FragmentSpread as GQLFragmentSpread
from wandb_graphql.language.ast import Node as GQLNode
from wandb_graphql.language.ast import OperationDefinition as GQLOperationDefinition
from wandb_graphql.language.ast import SelectionSet as GQLSelectionSet

CONFIG_DICT = ConfigDict(alias_generator=to_camel)


@pydantic_dataclass(frozen=True, config=CONFIG_DICT)
class SchemaInfo:
    """Information about supported types and fields from schema introspection."""

    types: list[TypeInfo]


@pydantic_dataclass(frozen=True, config=CONFIG_DICT)
class TypeInfo:
    """Information about a GraphQL type."""

    name: str
    fields: list[FieldInfo] | None = None


@pydantic_dataclass(frozen=True, config=CONFIG_DICT)
class FieldInfo:
    """Information about a GraphQL field."""

    name: str
    type_: TypeRef = Field(alias="type")


@pydantic_dataclass(frozen=True, config=CONFIG_DICT)
class TypeRef:
    """Information about a GraphQL type reference."""

    kind: str
    name: str | None = None
    of_type: TypeRef | None = Field(default=None, alias="ofType")


def gql_compat(query: GQLDocument | str, schema_info: SchemaInfo) -> GQLDocument:
    """Rewrite a GraphQL query to be compatible with the server schema.

    Args:
        query: The GraphQL query document to rewrite
        schema_info: Parsed schema info for the server

    Returns:
        Rewritten query document with only supported fields
    """
    gql_query = gql(query) if isinstance(query, str) else query
    return CompatibleGQLRewriter(schema=schema_info).rewrite(gql_query)


@pydantic_dataclass(config=CONFIG_DICT, repr=False)
class CompatibleGQLRewriter:
    """Class for rewriting GraphQL queries to be compatible with older servers."""

    schema: SchemaInfo

    #: maps {type_name -> {field_name -> field_info}}
    fields_by_type: dict[str, dict[str, FieldInfo] | None] = Field(init=False)

    #: names of fragments that are/aren't supported by the server
    invalid_fragments: set[str] = Field(default_factory=set, init=False)
    valid_fragments: set[str] = Field(default_factory=set, init=False)

    def __post_init__(self):
        # Build lookup of allowed fields by type
        self.fields_by_type = {
            typ.name: ({fld.name: fld for fld in typ.fields} if typ.fields else None)
            for typ in self.schema.types
        }

    @property
    def valid_types(self) -> set[str]:
        """Names of types supported by the server."""
        return set(self.fields_by_type)

    def _check_fragment_definitions(self, node: GQLDocument) -> None:
        """Check all fragment definitions to see if they are defined on types supported by the server."""
        for defn in node.definitions:
            if isinstance(defn, GQLFragmentDefinition):
                if defn.type_condition.name.value in self.valid_types:
                    self.valid_fragments.add(defn.name.value)
                else:
                    self.invalid_fragments.add(defn.name.value)

    @singledispatchmethod
    def rewrite(
        self, node: Optional[GQLNode], *, parent_type: Optional[str] = None
    ) -> Optional[GQLNode]:
        """Base rewrite method for unhandled node types."""
        return node

    @rewrite.register
    def _rewrite_document(
        self, node: GQLDocument, *, parent_type: Optional[str] = None
    ) -> Optional[GQLDocument]:
        # First pass: identify all invalid fragments
        self._check_fragment_definitions(node)

        # Second pass: rewrite definitions
        node.definitions = [
            new_defn
            for defn in node.definitions
            if (new_defn := self.rewrite(defn, parent_type=parent_type)) is not None
        ]
        return node

    @rewrite.register
    def _rewrite_fragment_defn(
        self, node: GQLFragmentDefinition, *, parent_type: Optional[str] = None
    ) -> Optional[GQLFragmentDefinition]:
        # E.g.
        #   fragment myFragment on SupportedType {
        #       __typename
        #       supportedFragmentField
        #       unsupportedFragmentField
        #   }

        # Skip fragments that were identified as invalid
        if node.name.value in self.invalid_fragments:
            return None

        parent_type = node.type_condition.name.value
        node.selection_set = self.rewrite(node.selection_set, parent_type=parent_type)
        if node.selection_set is None:
            return None
        return node

    @rewrite.register
    def _rewrite_operation_defn(
        self, node: GQLOperationDefinition, *, parent_type: Optional[str] = None
    ) -> Optional[GQLOperationDefinition]:
        parent_type = self._get_operation_type(node.operation)
        node.selection_set = self.rewrite(node.selection_set, parent_type=parent_type)
        return node

    @rewrite.register
    def _rewrite_selection_set(
        self, node: GQLSelectionSet, *, parent_type: Optional[str] = None
    ) -> Optional[GQLSelectionSet]:
        node.selections = [
            new_sel
            for sel in node.selections
            if (new_sel := self.rewrite(sel, parent_type=parent_type)) is not None
        ]

        # An empty selection set is invalid and should be removed
        if not node.selections:
            return None
        return node

    @rewrite.register
    def _rewrite_fragment_spread(
        self, node: GQLFragmentSpread, *, parent_type: Optional[str] = None
    ) -> Optional[GQLFragmentSpread]:
        # Skip removed fragments OR undefined fragments
        name: str = node.name.value
        if (name in self.invalid_fragments) or (name not in self.valid_fragments):
            return None
        return node

    @rewrite.register
    def _rewrite_field(
        self, node: GQLField, *, parent_type: Optional[str] = None
    ) -> Optional[GQLField]:
        # Special handling for __typename: we'll have to make this more
        # extensible if the need arises
        if node.name.value == "__typename":
            parent_type = "String"
        else:
            # Skip unsupported fields
            allowed_fields = set(self.fields_by_type.get(parent_type) or {})
            if node.name.value not in allowed_fields:
                return None
            # Get return type for field
            parent_type = self._get_field_type(parent_type, node.name.value)

        # If the field has no selection set, it's a leaf node and we can return it as-is
        if not node.selection_set:
            return node

        # Otherwise, the rewritten selection set must be non-empty
        node.selection_set = self.rewrite(node.selection_set, parent_type=parent_type)
        if not node.selection_set:
            return None
        return node

    def _get_operation_type(self, operation: str) -> str:
        """Get the type name for a given operation name."""
        # May need to generalize this later if needed
        if operation == "mutation":
            return "Mutation"
        if operation == "query":
            return "Query"
        raise ValueError(f"Unsupported operation: {operation}")

    def _get_field_type(self, parent_type: str, field_name: str) -> str | None:
        """Get the type name for a field name on a given parent type name."""
        try:
            field: FieldInfo = self.fields_by_type[parent_type][field_name]
        except (KeyError, TypeError):
            return None

        # Unwrap NonNull and List wrappers to get the named type
        field_type = field.type_
        while type_ref := field_type.of_type:
            field_type = type_ref

        return field_type.name
