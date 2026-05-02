from __future__ import annotations

from typing import Any

import pytest
from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


def test_execute_graphql_builds_api_request():
    api = ServiceApi.__new__(ServiceApi)
    api._timeout = None
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

    result = api.execute_graphql(
        """#graphql
            query UnitTest($name: String!) {
                viewer {
                    username
                }
        }
        """,
        {"name": "abc"},
        timeout=3,
    )

    assert result == {"ok": True}
    assert sent["timeout"] == 3
    assert sent["request"].graphql_request.query.startswith("#graphql")
    assert sent["request"].graphql_request.variables_json == '{"name": "abc"}'


def test_execute_graphql_propagates_core_api_error_response():
    api = ServiceApi.__new__(ServiceApi)
    api._timeout = None
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
