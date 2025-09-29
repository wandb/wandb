"""Definitions and utilities for client-side handling of "relay-style" GraphQL types for pagination.

For formal specs and definitions, see: https://relay.dev/graphql/connections.htm
"""

from typing import Generic, Iterator, List, Literal, Optional, TypeVar

from pydantic import NonNegativeInt

from .base import GQLResult

NodeT = TypeVar("NodeT", bound=GQLResult)
"""A generic type variable for a GraphQL relay node."""


class PageInfo(GQLResult):
    typename__: Literal["PageInfo"] = "PageInfo"
    end_cursor: Optional[str]
    has_next_page: bool


class Edge(GQLResult, Generic[NodeT]):
    node: NodeT


class Connection(GQLResult, Generic[NodeT]):
    edges: List[Edge[NodeT]]
    page_info: PageInfo

    def nodes(self) -> Iterator[NodeT]:
        """Returns an iterator over the nodes in the connection."""
        return (node for edge in self.edges if (node := edge.node))

    @property
    def has_next(self) -> bool:
        """Returns True if there are more pages to fetch."""
        return self.page_info.has_next_page

    @property
    def next_cursor(self) -> Optional[str]:
        """Returns the start cursor for the next page to fetch."""
        return self.page_info.end_cursor


class ConnectionWithTotal(Connection[NodeT], Generic[NodeT]):
    total_count: NonNegativeInt
