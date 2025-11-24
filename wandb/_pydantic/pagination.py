"""Utilities for client-side handling of "relay-style" GraphQL pagination.

For formal specs and definitions, see https://relay.dev/graphql/connections.htm.
"""

# Older-style type annotations required for Pydantic v1 / python 3.8 compatibility.
# ruff: noqa: UP006, UP045

from __future__ import annotations

from typing import Any, Generic, Iterator, List, Literal, Optional, TypeVar

from pydantic import NonNegativeInt, ValidationError
from typing_extensions import Self

from wandb._iterutils import PathLookupError, get_path
from wandb._strutils import nameof
from wandb.errors import ResponseError

from .base import GQLResult

# NodeT = TypeVar("NodeT", bound=GQLResult)
NodeT = TypeVar("NodeT")
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
    total_count: Optional[NonNegativeInt] = None

    def nodes(self) -> Iterator[NodeT]:
        """Returns an iterator over the nodes in the connection."""
        return (node for edge in self.edges if (node := edge.node))

    @property
    def has_next(self) -> bool:
        """Returns True if there are more pages to fetch."""
        return self.page_info.has_next_page

    @property
    def next_cursor(self) -> str | None:
        """Returns the start cursor for the next page to fetch."""
        return self.page_info.end_cursor

    @classmethod
    def from_result(cls, data: dict[str, Any], *path: int | str) -> Self:
        """Instantiate from the nested GraphQL response data, under the given path."""
        try:
            return cls.model_validate(get_path(data, *path))
        except (PathLookupError, ValidationError) as e:
            msg = f"{nameof(type(e))!r} on parsing {nameof(type(cls))!r} response data: {e}"
            raise ResponseError(msg) from e


class ConnectionWithTotal(Connection[NodeT], Generic[NodeT]):
    total_count: NonNegativeInt
