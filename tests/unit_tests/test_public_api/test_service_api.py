from types import SimpleNamespace
from typing import Any

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


def test_send_api_request_rebinds_after_session_connection_is_closed(monkeypatch):
    class FakeConnection:
        def __init__(self, api_id: str):
            self.api_id = api_id
            self.closed = False
            self.init_calls = 0
            self.request_api_ids: list[str] = []

        def api_init_request(self, settings: Any) -> SimpleNamespace:
            self.init_calls += 1
            return SimpleNamespace(api_id=self.api_id)

        def api_request(
            self,
            request: apb.ApiRequest,
            timeout: float | None = None,
        ) -> apb.ApiResponse:
            self.request_api_ids.append(request.api_id)
            return apb.ApiResponse()

        def api_cleanup_request(self, api_id: str) -> None:
            pass

    class FakeSetup:
        def __init__(self, connection: FakeConnection):
            self.connection = connection

        def ensure_service(self) -> FakeConnection:
            return self.connection

    first_connection = FakeConnection("first-api-id")
    second_connection = FakeConnection("second-api-id")
    setup = FakeSetup(first_connection)
    monkeypatch.setattr(service_api.wandb_setup, "singleton", lambda: setup)

    api = ServiceApi(Settings())
    api.send_api_request(apb.ApiRequest())

    setup.connection = second_connection
    api.send_api_request(apb.ApiRequest())

    first_connection.closed = True
    setup.connection = second_connection
    api.send_api_request(apb.ApiRequest())

    assert first_connection.init_calls == 1
    assert first_connection.request_api_ids == ["first-api-id", "first-api-id"]
    assert second_connection.init_calls == 1
    assert second_connection.request_api_ids == ["second-api-id"]
