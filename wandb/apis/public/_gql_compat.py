from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import singledispatchmethod
from textwrap import indent
from types import NoneType

from wandb_graphql import GraphQLScalarType, build_client_schema, print_ast
from wandb_graphql.language import ast
from wandb_graphql.type import GraphQLField, GraphQLObjectType, GraphQLSchema
from wandb_graphql.type.definition import GraphQLType
from wandb_graphql.type.introspection import TypeNameMetaFieldDef


@dataclass
class TypeInfo:
    """Contains information about available types and fields from schema."""

    # type_name -> {field_names}
    types: defaultdict[str, set[str]]

    # type_name -> field_name -> {arg_names}
    arguments: defaultdict[str, dict[str, set[str]]]


def indented_ast(node: ast.Node) -> str:
    return indent(print_ast(node), "  ")


def build_type_info(schema: GraphQLSchema) -> TypeInfo:
    """Builds a mapping of all types and their available fields/arguments."""
    types: defaultdict[str, set[str]] = defaultdict(set)
    arguments: defaultdict[str, dict[str, set[str]]] = defaultdict(dict)

    type_map = schema.get_type_map()

    for type_name, type_def in type_map.items():
        if isinstance(type_def, GraphQLObjectType):
            for field_name, field in type_def.fields.items():
                types[type_name].add(field_name)

                if isinstance(field, GraphQLField) and (arg_names := field.args):
                    arguments[type_name][field_name] = set(arg_names)

    return TypeInfo(types=types, arguments=arguments)


def ensure_graphql_schema(schema: GraphQLSchema) -> GraphQLSchema:
    """Ensures a schema is a GraphQLSchema."""
    return build_client_schema(schema) if isinstance(schema, dict) else schema


class GQLRequestRewriter:
    """Rewrites GraphQL queries to be compatible with server capabilities."""

    schema: GraphQLSchema

    root_types: dict[str, ast.OperationDefinition]
    type_info: TypeInfo
    fragment_defns: dict[str, ast.FragmentDefinition]

    def __init__(self, schema: GraphQLSchema):
        """Initialize with either a raw introspection result or GraphQLSchema."""
        gql_schema = ensure_graphql_schema(schema)

        self.schema = gql_schema
        self.type_info = build_type_info(gql_schema)
        self.root_types = {
            "query": gql_schema.get_query_type(),
            "mutation": gql_schema.get_mutation_type(),
        }
        self.fragment_defns = {}

    @singledispatchmethod
    def rewrite(self, node: ast.Node, *_) -> ast.Node:
        raise TypeError(f"Unknown node type {type(node)}: {node!r}")

    @rewrite.register(type(None))
    def _(self, node: NoneType, *_) -> None:
        return node

    @rewrite.register(ast.SelectionSet)
    def _(self, selection_set: ast.SelectionSet, parent_type: str) -> ast.SelectionSet:
        """Rewrites a selection set to only include supported fields."""
        # if (selection_set is None) or (not selection_set.selections):
        #     return selection_set

        if not selection_set.selections:
            return selection_set

        return ast.SelectionSet(
            selections=[
                new_item
                for item in selection_set.selections
                if (new_item := self.rewrite(item, parent_type)) is not None
            ]
        )

    # ---------------------------------------------------------------------------
    @rewrite.register(ast.Field)
    def _(self, field: ast.Field, parent_type: str) -> ast.Field | None:
        # Skip if field isn't supported
        field_name = field.name.value

        # Special exception for fields like __typename
        if (field_name != "__typename") and (
            field_name not in self.type_info.types[parent_type]
        ):
            return None

        # Filter arguments
        new_arguments = []
        if field.arguments:
            field_args = self.type_info.arguments[parent_type][field_name]
            new_arguments = [
                arg for arg in field.arguments if (arg.name.value in field_args)
            ]

        # Get return type for nested selections
        field_type = self._get_field_type_name(parent_type, field_name)

        new_selection_set = self.rewrite(field.selection_set, field_type)

        # Fields can have a null selection set, just not an empty one
        if (new_selection_set is None) or new_selection_set.selections:
            return ast.Field(
                name=field.name,
                alias=field.alias,
                arguments=new_arguments,
                directives=field.directives,
                selection_set=new_selection_set,
            )

        return None

    @rewrite.register(ast.FragmentSpread)
    def _(self, node: ast.FragmentSpread, *_) -> ast.FragmentSpread | None:
        if self._fragment_type_name(node.name.value) is not None:
            return node
        return None

    @rewrite.register(ast.InlineFragment)
    def _(self, node: ast.InlineFragment, *_) -> ast.InlineFragment | None:
        # Handle inline fragments
        selection_set = node.selection_set  # Fields selected in fragment
        on_type = node.type_condition.name.value  # Type on which fragment is defined

        new_selection_set = self.rewrite(selection_set, on_type)
        if new_selection_set.selections:
            return ast.InlineFragment(
                type_condition=node.type_condition,
                directives=node.directives,
                selection_set=new_selection_set,
            )

        return None

    def _get_field_type_name(self, parent_type: str, field_name: str) -> str | None:
        """Gets the type name for a field on a given type."""
        type_def = self._get_field_type_def(parent_type, field_name)

        if isinstance(type_def, GraphQLObjectType):
            if field := type_def.fields.get(field_name):
                return str(field.type)

            raise ValueError(
                f"Unable to get type name for field {field_name!r} on type {parent_type!r}"
            )

        if isinstance(type_def, GraphQLScalarType):
            return type_def.name

        raise ValueError(f"Unknown type: {type(type_def)}")

    def _get_field_type_def(self, parent_type: str, field_name: str) -> GraphQLType:
        if field_name == "__typename":
            # Special handling for e.g. `__typename`.  Extend this if needed.
            return self.schema.get_type(TypeNameMetaFieldDef.type.of_type.name)

        return self.schema.get_type(parent_type)

    def _fragment_type_name(self, fragment_name: str) -> str | None:
        """Gets the name of the type on which the fragment is defined."""
        if (frag_defn := self.fragment_defns.get(fragment_name)) and (
            orig_type := self.schema.get_type(frag_defn.type_condition.name.value)
        ):
            return orig_type.name
        return None

    @rewrite.register(ast.Document)
    def _rewrite_query(self, query: ast.Document, *_) -> ast.Document:
        """Rewrites a GraphQL query string to be compatible with the schema."""
        # Do a first pass to gather all the fragment definitions
        self.fragment_defns = self._gather_fragment_definitions(query)

        # Do a second pass to rewrite the query
        query.definitions = [
            new_defn
            for defn in query.definitions
            if (new_defn := self.rewrite(defn)) is not None
        ]
        return query

    @rewrite.register(ast.OperationDefinition)
    def _(self, defn: ast.OperationDefinition, *_) -> ast.OperationDefinition | None:
        if not (root_type := self.root_types.get(defn.operation)):
            raise ValueError(f"No root type found for operation:\n{indented_ast(defn)}")

        new_selection_set = self.rewrite(defn.selection_set, root_type.name)
        if new_selection_set.selections:
            defn.selection_set = new_selection_set
            return defn
        return None

    @rewrite.register(ast.FragmentDefinition)
    def _(self, defn: ast.FragmentDefinition, *_) -> ast.FragmentDefinition | None:
        if self._fragment_type_name(defn.name.value):
            new_selection_set = self.rewrite(
                defn.selection_set, defn.type_condition.name.value
            )
            if new_selection_set.selections:
                defn.selection_set = new_selection_set
                return defn

        return None

    # Fallbacks for unknown categories of node types
    @rewrite.register(ast.Selection)
    def _rewrite_selection(self, selection: ast.Selection, *_) -> ast.Selection | None:
        # Default/fallback: not a recognized/handled selection type
        raise TypeError(f"Unknown selection type {type(selection)}: {selection!r}")

    @rewrite.register(ast.Definition)
    def _rewrite_definition(self, defn: ast.Definition, *_) -> ast.Definition | None:
        # Default/fallback: not a recognized/handled definition type
        raise TypeError(f"Unknown definition type {type(defn).__qualname__}: {defn!r}")

    def _gather_fragment_definitions(self, document):
        return {
            defn.name.value: defn
            for defn in document.definitions
            if isinstance(defn, ast.FragmentDefinition)
        }


def rewrite_gql_request(schema: GraphQLSchema, query: ast.Document) -> ast.Document:
    """Rewrite a query to be compatible with the server schema."""
    return GQLRequestRewriter(schema).rewrite(query)
