"""GraphQL response builders and a transport stub shared by API contract tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock


def _trigger(
    name: str,
    *,
    event_type: str = "CREATE_ARTIFACT",
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "__typename": "Trigger",
        "id": f"id-{name}",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": None,
        "name": name,
        "description": None,
        "enabled": True,
        "scope": {
            "__typename": "Project",
            "id": "UHJvamVjdDox",
            "name": "my-project",
        },
        "event": {
            "__typename": "FilterEventTriggeringCondition",
            "eventType": event_type,
            "filter": json.dumps({"filter": {"$or": [{"$and": []}]}}),
        },
        "action": action
        if action is not None
        else {"__typename": "NoOpTriggeredAction", "noOp": True},
    }


def _connection(
    nodes: list[Any], *, end_cursor: str | None = None, has_next: bool = False
) -> dict[str, Any]:
    return {
        "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next},
        "edges": [{"node": node} for node in nodes],
    }


def _service_api(*responses: dict[str, Any] | Exception) -> MagicMock:
    """A fake `ServiceApi` that returns each response in turn.

    Like the real `execute_graphql`, it hands the serialized response to the
    `parse` callable it was given, so the tests exercise however the paginator
    chooses to parse each page.
    """
    pages = iter(responses)

    def execute_graphql(*_: Any, parse=json.loads, **__: Any) -> Any:
        response = next(pages)
        if isinstance(response, Exception):
            raise response
        return parse(json.dumps(response))

    service_api = MagicMock()
    service_api.execute_graphql.side_effect = execute_graphql
    return service_api
