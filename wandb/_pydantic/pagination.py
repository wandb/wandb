"""Utilities for client-side handling of "relay-style" GraphQL pagination.

For formal specs and definitions, see https://relay.dev/graphql/connections.htm.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Annotated, Any, Final, Generic, Literal, TypeAlias, TypeVar

from pydantic import GetCoreSchemaHandler, NonNegativeInt, PlainSerializer
from pydantic.alias_generators import to_camel
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function

from wandb._strutils import repr_join

from .base import GQLInput, GQLResult
from .utils import to_json

NodeT = TypeVar("NodeT")
"""A generic type variable for a GraphQL relay node."""


ORDER_REGEX: Final[re.Pattern[str]] = re.compile(
    r"""
    \A              # Absolute start of string, multiline not allowed
    ([+-])?         # Optional leading sign
    ([a-zA-Z_]\w*)  # Field name (must start with a non-numeric character)
    \Z              # Absolute end of string, multiline not allowed
    """,
    flags=re.VERBOSE | re.ASCII,
)


FilterDict: TypeAlias = Annotated[dict[str, Any], PlainSerializer(to_json)]
"""A paginator filter mapping serialized as JSON for GraphQL variables."""


@dataclass(frozen=True, slots=True)
class OrderValidator:
    """Pydantic metadata that validates and normalizes an `order` argument."""

    valid: Collection[str] | None = None
    """The allowed field names. If None, all fields are allowed."""

    def __post_init__(self) -> None:
        if valid := self.valid:
            object.__setattr__(self, "valid", frozenset(valid))

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return no_info_after_validator_function(self.validate, handler(source_type))

    def validate(self, order: str) -> str:
        # Parse the components of the order string
        if (m := ORDER_REGEX.match(order)) is None:
            raise ValueError(f"Invalid order string: {order!r}")

        sign, name = m.groups()

        # Check if the field name (without the sign) is allowed
        if (valid := self.valid) and (name not in valid):
            msg = f"Invalid order field {name!r}, must be one of: {repr_join(sorted(valid))}"
            raise ValueError(msg)

        # Default to ascending order
        return f"{sign or '+'}{name}"


class PaginatorVars(GQLInput, alias_generator=to_camel):
    pass


class PageInfo(GQLResult):
    """Pagination metadata returned by the server for a single page of results."""

    typename__: Literal["PageInfo"] = "PageInfo"

    end_cursor: str | None
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

    total_count: NonNegativeInt | None = None
    """Total number of results across all pages, if available."""

    def nodes(self) -> Iterator[NodeT]:
        """Returns an iterator over the nodes in the connection."""
        return (node for edge in self.edges if (node := edge.node))

    @property
    def has_next(self) -> bool:
        """Returns True if there are more pages to fetch."""
        return self.page_info.has_next_page

    @property
    def next_cursor(self) -> str | None:
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
