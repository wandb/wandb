"""Definitions and utilities for parsing GraphQL relay-style paginated responses."""

from typing import Generic, Iterator, List, Optional, TypeVar

from pydantic import NonNegativeInt

from .base import GQLResult
from .v1_compat import to_camel

T = TypeVar("T")


class GQLPageInfo(GQLResult, alias_generator=to_camel, extra="forbid"):
    end_cursor: Optional[str]
    has_next_page: bool


class GQLEdge(GQLResult, Generic[T], alias_generator=to_camel, extra="allow"):
    node: T
    cursor: Optional[str] = None


class GQLConnection(GQLResult, Generic[T], alias_generator=to_camel, extra="allow"):
    edges: List[GQLEdge[T]]
    page_info: GQLPageInfo

    def nodes(self) -> Iterator[T]:
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


class GQLConnectionWithCount(GQLConnection[T], alias_generator=to_camel):
    total_count: NonNegativeInt
