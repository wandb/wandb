from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import InitVar, field
from itertools import chain
from typing import (
    Any,
    Callable,
    Iterable,
    Iterator,
    List,
    Protocol,
    Sequence,
    TypeVar,
    runtime_checkable,
)

from pydantic import AliasPath, ConfigDict, PositiveInt, TypeAdapter, ValidationError
from pydantic.dataclasses import dataclass as pydantic_dataclass
from wandb_graphql.language.ast import Document

from wandb.sdk.automations import Automation
from wandb.sdk.automations._generated import (
    PaginatedIntegrations,
    PaginatedProjectsWithTriggers,
    SlackIntegration,
    WebhookIntegration,
)
from wandb.sdk.automations._generated.fragments import PageInfo

T = TypeVar("T")

Integration = TypeVar("Integration", SlackIntegration, WebhookIntegration)
IntegrationListAdapter = TypeAdapter(List[Integration])
AutomationListAdapter = TypeAdapter(List[Automation])


# Structural type hints to make pydantic and mypy happy
class _Connection(Protocol):
    edges: list[Any]
    page_info: PageInfo


@runtime_checkable
class _Client(Protocol):
    execute: Callable[[...], Any]


def _identity(x: T) -> T:
    """Return the input argument, untouched."""
    return x


# NOTE: This borrows heavily from the `Paginator` class but is ultimately a
# separate implementation, in order to reduce the risk of breaking existing
# behavior of `ArtifactCollections`, `Artifacts`, `Projects`, etc.
@pydantic_dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class _PydanticPaginator(ABC, Iterator[T]):
    """A paginator that uses pydantic models to validate the page data."""

    client: _Client  #: The GraphQL client to use for executing the query.

    query: Document  #: The GraphQL query to execute for each page.
    variables: dict[str, Any]  #: The query-specific variables to pass to the query.
    per_page: PositiveInt = 50  #: The number of items to fetch per page.

    #: The path to the page data in the response.
    page_path: InitVar[Sequence[str | int] | None] = None

    #: A callback to extract the page data from the raw response.
    get_page: Callable[[dict[str, Any]], Any] = field(default=_identity, init=False)

    #: Info about the last page of items fetched, if any.
    last_page: PageInfo | None = field(default=None, init=False)

    def __post_init__(self, page_path: Sequence[str | int] | None):
        if page_path:
            self.get_page = AliasPath(*page_path).search_dict_for_path

    @property
    def more(self) -> bool:
        """Whether there are more items to fetch."""
        return (prev := self.last_page) is None or prev.has_next_page

    @property
    def cursor(self) -> str | None:
        """The start cursor to use for the next page."""
        return None if (self.last_page is None) else self.last_page.end_cursor

    def __iter__(self) -> Iterator[T]:
        while self.more:
            data = self._fetch_page_data()
            page = self._parse_page_data(data)
            objs = self._parse_page_objs(page)

            yield from objs

            self.last_page = page.page_info

    def __next__(self) -> T:
        return next(self)

    def _fetch_page_data(self) -> dict[str, Any]:
        """Fetch the raw response data for the current page."""
        # Combine page-specific and common variables
        params = {**self.variables, "cursor": self.cursor, "perPage": self.per_page}
        return self.client.execute(self.query, variable_values=params)

    @abstractmethod
    def _parse_page_data(self, data: dict[str, Any]) -> _Connection:
        """Parse the raw response data into a paginated connection object."""
        raise NotImplementedError

    @abstractmethod
    def _parse_page_objs(self, page: _Connection) -> Iterable[T]:
        """Parse the page data into a list of objects."""
        raise NotImplementedError


class Automations(_PydanticPaginator[Automation]):
    def _parse_page_data(self, data: dict[str, Any]) -> PaginatedProjectsWithTriggers:
        """Parse the raw response data into a paginated connection object."""
        try:
            page_data = self.get_page(data)
            return PaginatedProjectsWithTriggers.model_validate(page_data)
        except ValidationError as e:
            raise ValueError(f"Unexpected response data: {data!r}") from e

    def _parse_page_objs(
        self, page: PaginatedProjectsWithTriggers
    ) -> Iterable[Automation]:
        """Parse the page data into a list of objects."""
        return AutomationListAdapter.validate_python(
            chain.from_iterable(edge.node.triggers for edge in page.edges)
        )


class Integrations(_PydanticPaginator[Integration]):
    def _parse_page_data(self, data: dict[str, Any]) -> PaginatedIntegrations:
        """Parse the raw response data into a paginated connection object."""
        try:
            page_data = self.get_page(data)
            return PaginatedIntegrations.model_validate(page_data)
        except ValidationError as e:
            raise ValueError(f"Unexpected response data: {data!r}") from e

    def _parse_page_objs(self, page: PaginatedIntegrations) -> Iterable[Integration]:
        """Parse the page data into a list of objects."""
        return IntegrationListAdapter.validate_python(edge.node for edge in page.edges)
