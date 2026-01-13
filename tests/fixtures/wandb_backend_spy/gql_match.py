"""GraphQL request matchers and responders."""

from __future__ import annotations

import abc
import dataclasses
import json
import re
import threading

import fastapi
from typing_extensions import Any, TypeAlias, override

# Matches queries containing a line in one of the following forms:
#   mutation OpName(
#   mutation OpName{
#   query OpName(
#   query OpName{
_GQL_OPNAME_RE = re.compile(r"(?m)^(mutation|query)\s+(\w+)\s*[\(\{]")


# NOTE: In Python 3.12+, this would be done with a `type` statement.
GQLStub: TypeAlias = "tuple[Matcher, Responder]"


class Matcher:
    """An object that selects matching GQL requests.

    Matchers are stateless and always produce the same result for the same
    arguments.
    """

    def __init__(
        self,
        *,
        operation: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> None:
        self._operation = operation
        self._variables = variables or {}

    def matches(self, query: str, variables: dict[str, Any]) -> bool:
        """Returns whether this matches the GQL request."""
        query_match = _GQL_OPNAME_RE.search(query)

        if not query_match:
            return False

        opname = query_match.group(2)
        if self._operation is not None and self._operation != opname:
            return False

        for key, expected in self._variables.items():
            if key not in variables:
                return False
            if variables[key] != expected:
                return False

        return True


def any() -> Matcher:
    """A matcher that matches any request."""
    return Matcher()


@dataclasses.dataclass(frozen=True)
class Request:
    """The data in a GraphQL request."""

    query: str
    variables: dict[str, Any]


class Responder(abc.ABC):
    """An object that produces responses to GQL requests.

    Unlike matchers, responders may be stateful.
    Responder objects track all the times they were used.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._requests: list[Request] = []

    @property
    def total_calls(self) -> int:
        """The number of times this responder was used."""
        with self._lock:
            return len(self._requests)

    @property
    def requests(self) -> list[Request]:
        """All requests handled, in order."""
        with self._lock:
            return list(self._requests)

    def respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        """Respond to a matched GraphQL request.

        Args:
            query: The raw GQL query from the request.
            variables: The variables in the request.

        Returns:
            A response, or None to let a request be handled by the backend or
            other responders.
        """
        with self._lock:
            self._requests.append(Request(query=query, variables=variables))
            return self._respond(query, variables)

    @abc.abstractmethod
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        """Subclass implementation of `respond`.

        Always called with `self._lock` held.
        """


class Capture(Responder):
    """Detects that a request was matched, then passes it through."""

    @override
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        return None


class Constant(Responder):
    """A constant value to always respond with."""

    def __init__(
        self,
        *,
        content: str | dict[str, Any],
        status: int = 200,
    ):
        super().__init__()
        if isinstance(content, str):
            self._content = content
        else:
            self._content = json.dumps(content)

        self._status = status

    @override
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        return fastapi.Response(
            self._content,
            status_code=self._status,
        )


class Sequence(Responder):
    """A sequence of responses to use.

    Responses are returned in order; None values cause the corresponding
    request to be passed through to the backend or to other responders.
    After all responses are exhausted, all requests are passed through.
    """

    def __init__(self, responders: list[Responder | None]):
        super().__init__()
        self._responders = iter(responders)

    @override
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        responder = next(self._responders, None)

        if not responder:
            return None

        return responder.respond(query, variables)


def once(
    *,
    content: str | dict[str, Any],
    status: int = 200,
) -> Responder:
    """Respond to the first request and pass through all the rest.

    Same arguments as for Constant.
    """
    return Sequence([Constant(content=content, status=status)])
