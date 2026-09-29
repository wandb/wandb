from typing import Any

import pytest
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


def test_project_internal_id_sends_typed_request_and_timeout():
    api = ServiceApi(Settings())
    sent: dict[str, Any] = {}

    def send_api_request(
        request: apb.ApiRequest,
        timeout: float | None = None,
    ) -> apb.ApiResponse:
        sent["request"] = request
        sent["timeout"] = timeout
        return apb.ApiResponse(
            get_project_internal_id_response=apb.GetProjectInternalIdResponse(
                project_internal_id="opaque-project-id"
            )
        )

    api.send_api_request = send_api_request

    project_internal_id = api.project_internal_id(
        entity="entity",
        project="project",
        timeout=3,
    )

    assert project_internal_id == "opaque-project-id"
    assert sent["timeout"] == 3
    request = sent["request"].get_project_internal_id_request
    assert request.entity == "entity"
    assert request.project == "project"


def test_project_internal_id_returns_none_when_project_is_missing():
    api = ServiceApi(Settings())

    def send_api_request(
        request: apb.ApiRequest,
        timeout: float | None = None,
    ) -> apb.ApiResponse:
        return apb.ApiResponse(
            get_project_internal_id_response=apb.GetProjectInternalIdResponse()
        )

    api.send_api_request = send_api_request

    assert api.project_internal_id(entity="entity", project="project") is None
