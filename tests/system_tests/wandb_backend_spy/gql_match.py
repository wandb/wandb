"""GraphQL request matchers and responders."""

from __future__ import annotations

import abc
import json
import re
import sys
import threading
from typing import Any

import fastapi

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

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
        operation: str,
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
        if self._operation != opname:
            return False

        for key, expected in self._variables.items():
            if key not in variables:
                return False
            if variables[key] != expected:
                return False

        return True


class Responder(abc.ABC):
    """An object that produces responses to GQL requests.

    Unlike matchers, responders may be stateful.
    Responder objects track all the times they were used.
    """

    def __init__(self) -> None:
        super().__init__()
        self._total_calls = 0

    @property
    def total_calls(self) -> int:
        """The number of times this responder was used."""
        return self._total_calls

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
        self._total_calls += 1
        return self._respond(query, variables)

    @abc.abstractmethod
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None: ...


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
        self._lock = threading.Lock()
        self._responders = iter(responders)

    @override
    def _respond(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> fastapi.Response | None:
        with self._lock:
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
