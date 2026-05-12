from unittest import mock

from wandb.apis.public.service_api import ServiceApi
from wandb.proto.wandb_api_pb2 import ApiResponse, GraphQLResponse


def test_execute_graphql_sends_query_unchanged_and_timeout():
    api = ServiceApi(mock.MagicMock())
    api.send_api_request = mock.MagicMock(
        return_value=ApiResponse(
            graphql_response=GraphQLResponse(data_json='{"ok": true}')
        )
    )

    query = "#graphql\nquery Viewer { viewer { id } }"

    assert api.execute_graphql(query, {"x": 1}, timeout=3) == {"ok": True}

    request = api.send_api_request.call_args.args[0]
    assert request.graphql_request.query == query
    assert request.graphql_request.variables_json == '{"x": 1}'
    assert api.send_api_request.call_args.kwargs == {"timeout": 3}
