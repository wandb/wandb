import gc
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from wandb.apis.public import service_api
from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError
from wandb.sdk.wandb_settings import Settings


def test_execute_graphql_sends_query_unchanged_and_timeout():
    api = ServiceApi(Settings())
    sent: dict[str, Any] = {}

    def send_api_request(
        request: apb.ApiRequest,
        timeout: float | None = None,
    ) -> apb.ApiResponse:
        sent["request"] = request
        sent["timeout"] = timeout
        return apb.ApiResponse(
            graphql_response=apb.GraphQLResponse(data_json='{"ok": true}')
        )

    api.send_api_request = send_api_request

    query = "#graphql\nquery Viewer { viewer { id } }"
    result = api.execute_graphql(query, {"x": 1}, timeout=3)

    assert result == {"ok": True}
    assert sent["timeout"] == 3
    assert sent["request"].graphql_request.query == query
    assert sent["request"].graphql_request.variables_json == '{"x": 1}'


def test_execute_graphql_propagates_core_api_error_response():
    api = ServiceApi(Settings())
    error_response = apb.ApiErrorResponse(message="server unavailable")

    def send_api_request(
        request: apb.ApiRequest,
        timeout: float | None = None,
    ) -> apb.ApiResponse:
        raise WandbApiFailedError(error_response.message, error_response)

    api.send_api_request = send_api_request

    with pytest.raises(WandbApiFailedError, match="server unavailable") as exc_info:
        api.execute_graphql("query Viewer { viewer { id } }")

    assert exc_info.value.response is error_response


def _mock_service(monkeypatch) -> Mock:
    """Back _get_api_session() with a mock connection and return it."""
    connection = Mock()
    connection.api_init_request.return_value = SimpleNamespace(api_id="api-1")
    monkeypatch.setattr(
        service_api.wandb_setup,
        "singleton",
        lambda: SimpleNamespace(ensure_service=lambda: connection),
    )
    return connection


def test_cleanup_finalizer_runs_in_owner_process(monkeypatch):
    connection = _mock_service(monkeypatch)

    api = ServiceApi(Settings())
    api._get_api_session()

    del api
    gc.collect()

    connection.api_cleanup_request.assert_called_once_with("api-1")


def test_cleanup_finalizer_skips_forked_child(monkeypatch):
    connection = _mock_service(monkeypatch)

    api = ServiceApi(Settings())
    api._get_api_session()  # the finalizer records this process's pid

    # Simulate cyclic GC collecting the inherited ServiceApi in a forked child,
    # where the owning asyncio thread is gone and the cleanup request would
    # otherwise block forever.
    child_pid = os.getpid() + 1
    monkeypatch.setattr(os, "getpid", lambda: child_pid)

    del api
    gc.collect()

    connection.api_cleanup_request.assert_not_called()
