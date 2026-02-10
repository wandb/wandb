from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sized
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, overload

import wandb
from wandb._strutils import nameof

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb._pydantic import Connection
    from wandb.apis.public.api import RetryingClient

_WandbT = TypeVar("_WandbT")
"""Generic type variable for a W&B object."""

_NodeT = TypeVar("_NodeT")
"""Generic type variable for a parsed GraphQL relay node."""


class Paginator(Iterator[_WandbT], ABC):
    """An iterator for paginated objects from GraphQL requests."""

    QUERY: Document | ClassVar[Document | None]

    def __init__(
        self,
        client: RetryingClient,
        variables: Mapping[str, Any],
        per_page: int = 50,  # We don't allow unbounded paging
    ):
        self.client = client

        # shallow copy partly guards against mutating the original input
        self.variables: dict[str, Any] = dict(variables)

        self.per_page: int = per_page
        self.objects: list[_WandbT] = []
        self.index: int = -1
        self.last_response: object | None = None

    def __iter__(self) -> Iterator[_WandbT]:
        self.index = -1
        return self

    @property
    @abstractmethod
    def more(self) -> bool:
        """Whether there are more pages to be fetched."""
        raise NotImplementedError

    @property
    @abstractmethod
    def cursor(self) -> str | None:
        """The start cursor to use for the next fetched page."""
        raise NotImplementedError

    @abstractmethod
    def convert_objects(self) -> Iterable[_WandbT]:
        """Convert the last fetched response data into the iterated objects."""
        raise NotImplementedError

    def update_variables(self) -> None:
        """Update the query variables for the next page fetch."""
        self.variables.update({"perPage": self.per_page, "cursor": self.cursor})

    def _update_response(self) -> None:
        """Fetch and store the response data for the next page."""
        self.last_response = self.client.execute(
            self.QUERY, variable_values=self.variables
        )

    def _load_page(self) -> bool:
        """Fetch the next page, if any, returning True and storing the response if there was one."""
        if not self.more:
            return False
        self.update_variables()
        self._update_response()
        self.objects.extend(self.convert_objects())
        return True

    @overload
    def __getitem__(self, index: int) -> _WandbT: ...
    @overload
    def __getitem__(self, index: slice) -> list[_WandbT]: ...

    def __getitem__(self, index: int | slice) -> _WandbT | list[_WandbT]:
        loaded = True
        stop = index.stop if isinstance(index, slice) else index
        while loaded and stop > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self) -> _WandbT:
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
            if len(self.objects) <= self.index:
                raise StopIteration
        return self.objects[self.index]

    next = __next__


class SizedPaginator(Paginator[_WandbT], Sized, ABC):
    """A Paginator for objects with a known total count."""

    @property
    def length(self) -> int | None:
        wandb.termwarn(
            (
                "`.length` is deprecated and will be removed in a future version. "
                "Use `len(...)` instead."
            ),
            repeat=False,
        )
        return len(self)

    def __len__(self) -> int:
        if self._length is None:
            self._load_page()
        if self._length is None:
            raise ValueError("Object doesn't provide length")
        return self._length

    @property
    @abstractmethod
    def _length(self) -> int | None:
        raise NotImplementedError


class RelayPaginator(Paginator[_WandbT], Generic[_NodeT, _WandbT], ABC):
    """A Paginator for GQL relay-style nodes parsed via Pydantic.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: Connection[_NodeT] | None

    @property
    def more(self) -> bool:
        return (conn := self.last_response) is None or conn.has_next

    @property
    def cursor(self) -> str | None:
        return conn.next_cursor if (conn := self.last_response) else None

    @abstractmethod
    def _convert(self, node: _NodeT) -> _WandbT | Any:
        """Convert a parsed GraphQL node into the iterated object.

        If a falsey value is returned, it will be skipped during iteration.
        """
        raise NotImplementedError

    def convert_objects(self) -> Iterable[_WandbT]:
        # Default implementation. Subclasses can override this if if more complex
        # logic is needed, but ideally most shouldn't need to.
        if conn := self.last_response:
            yield from filter(None, map(self._convert, conn.nodes()))


class SizedRelayPaginator(RelayPaginator[_NodeT, _WandbT], Sized, ABC):
    """A Paginator for GQL nodes parsed via Pydantic, with a known total count.

    <!-- lazydoc-ignore-class: internal -->
    """

    last_response: Connection[_NodeT] | None

    def __len__(self) -> int:
        """Returns the total number of objects to expect."""
        # If the first page hasn't been fetched yet, do that first
        if self.last_response is None:
            self._load_page()
        if (conn := self.last_response) and (total := conn.total_count) is not None:
            return total
        raise NotImplementedError(f"{nameof(type(self))!r} doesn't provide length")
