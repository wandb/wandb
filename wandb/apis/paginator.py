from __future__ import annotations

from abc import abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Iterator,
    Mapping,
    Protocol,
    Sized,
    TypeVar,
    overload,
)

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

T = TypeVar("T")


# Structural type hint for the client instance
class _Client(Protocol):
    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


class Paginator(Iterator[T]):
    """An iterator for paginated objects from GraphQL requests."""

    QUERY: ClassVar[Document | None] = None

    def __init__(
        self,
        client: _Client,
        variables: Mapping[str, Any],
        per_page: int = 50,  # We don't allow unbounded paging
    ):
        self.client: _Client = client

        # shallow copy partly guards against mutating the original input
        self.variables: dict[str, Any] = dict(variables)

        self.per_page: int = per_page
        self.objects: list[T] = []
        self.index: int = -1
        self.last_response: object | None = None

    def __iter__(self) -> Iterator[T]:
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
    def convert_objects(self) -> list[T]:
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
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        loaded = True
        stop = index.stop if isinstance(index, slice) else index
        while loaded and stop > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self) -> T:
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
            if len(self.objects) <= self.index:
                raise StopIteration
        return self.objects[self.index]

    next = __next__


class SizedPaginator(Paginator[T], Sized):
    """A Paginator for objects with a known total count."""

    def __len__(self) -> int:
        if self.length is None:
            self._load_page()
        if self.length is None:
            raise ValueError("Object doesn't provide length")
        return self.length

    @property
    @abstractmethod
    def length(self) -> int | None:
        raise NotImplementedError
