"""Utilities for client-side handling of "relay-style" GraphQL pagination.

For formal specs and definitions, see https://relay.dev/graphql/connections.htm.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Generic, Literal, Optional, TypeVar

from pydantic import NonNegativeInt

from .base import GQLResult

NodeT = TypeVar("NodeT")
"""A generic type variable for a GraphQL relay node."""


class PageInfo(GQLResult):
    """Pagination metadata returned by the server for a single page of results."""

    typename__: Literal["PageInfo"] = "PageInfo"

    end_cursor: Optional[str]
    """Opaque token marking the end of this page and the start of the next page."""

    has_next_page: bool
    """True if more results exist beyond this page."""


class Edge(GQLResult, Generic[NodeT]):
    """A wrapper around a single result item in a paginated response.

    In relay-style pagination, individual items are wrapped in "edges" which can
    carry additional metadata, e.g., per-item cursors. This base implementation
    only exposes the `node` (the actual result item, like a GraphQL `Run` or `Project`).
    """

    node: NodeT
    """The actual result item."""


class Connection(GQLResult, Generic[NodeT]):
    """A page of results from the response of a paginated GraphQL query.

    This follows the "Relay Connection" specification, which is a standard
    way to paginate large result sets in GraphQL. Instead of returning all
    results at once, the server returns one page at a time. Each "page" is
    represented by a `Connection` object that includes:

    - A list of `edges`, each wrapping a single result item (`node`).
    - A `page_info` object with metadata for fetching subsequent pages.
    - Optionally, a `total_count` of all results (not just this page).
    """

    edges: list[Edge[NodeT]]
    """The items in this page, each wrapped in an `Edge`."""

    page_info: PageInfo
    """Pagination metadata, e.g. `end_cursor`, `has_next_page`."""

    total_count: Optional[NonNegativeInt] = None
    """Total number of results across all pages, if available."""

    def nodes(self) -> Iterator[NodeT]:
        """Returns an iterator over the nodes in the connection."""
        return (node for edge in self.edges if (node := edge.node))

    @property
    def has_next(self) -> bool:
        """Returns True if there are more pages to fetch."""
        return self.page_info.has_next_page

    @property
    def next_cursor(self) -> Optional[str]:
        """The cursor value to pass as the `after` arg in the next page request."""
        return self.page_info.end_cursor


class ConnectionWithTotal(Connection[NodeT], Generic[NodeT]):
    """A `Connection` where the `totalCount` field must be present.

    Use this INSTEAD of `Connection` when the paginated query is expected
    to return a finite `totalCount` field, i.e. when `totalCount` is:
    - explicitly requested in the GraphQL query
    - non-nullable in the GraphQL schema
    """

    total_count: NonNegativeInt
    """Total number of results across all pages (required, not optional)."""
