from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wandb_gql import gql
from wandb_graphql import visit
from wandb_graphql.language import ast
from wandb_graphql.language.visitor import Visitor


@dataclass
class CompatibleQueryRewriter(Visitor):
    supported_types: set[str]
    supported_fields: dict[str, set[str]]
    removed_fragments: set[str] = field(default_factory=set)
    used_fragments: set[str] = field(default_factory=set)

    def enter_FragmentDefinition(  # noqa: N802
        self, node: ast.FragmentDefinition, *_
    ) -> ast.FragmentDefinition | None:
        # Remove fragment if its type isn't supported
        if node.type_condition.name.value not in self.supported_types:
            self.removed_fragments.add(node.name.value)
            return None
        return node

    def enter_FragmentSpread(  # noqa: N802
        self, node: ast.FragmentSpread, *_
    ) -> ast.FragmentSpread | None:
        # Remove fragment spread if the fragment was removed
        if node.name.value in self.removed_fragments:
            return None
        self.used_fragments.add(node.name.value)
        return node

    def enter_Field(self, node: ast.Field, key, parent, *_) -> ast.Field | None:  # noqa: N802
        parent_type: str = parent[0].name.value
        if parent_type and parent_type in self.supported_fields:
            if node.name.value not in self.supported_fields[parent_type]:
                return None
        return node

    def leave_Document(self, node: ast.Document, *_) -> ast.Document:  # noqa: N802
        # Remove unused fragment definitions
        node.definitions = [
            d
            for d in node.definitions
            if not isinstance(d, ast.FragmentDefinition)
            or d.name.value in self.used_fragments
        ]
        return node


def rewrite_compatible_query(query: ast.Document, client: Any) -> ast.Document:
    """Rewrite a GraphQL query for backward server compatibility."""
    introspection_query = gql(
        """
        query GetSupportedTypes {
            __schema {
                types {
                    name
                    fields {name}
                }
            }
        }
        """
    )
    result = client.execute(introspection_query)
    types = result["__schema"]["types"]

    supported_types = {typ["name"] for typ in types}
    supported_fields = {
        typ["name"]: {f["name"] for f in fields}
        for typ in types
        if (fields := typ["fields"])
    }

    # Visit and modify the AST
    visitor = CompatibleQueryRewriter(supported_types, supported_fields)
    rewritten_query = visit(query, visitor)
    return rewritten_query
