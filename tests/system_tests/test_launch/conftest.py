import pytest
from wandb.apis.public.service_api import ServiceApi
from wandb.proto.wandb_api_pb2 import (
    ApiRequest,
    CreateRunQueueRequest,
    RunQueueOperationRequest,
)


@pytest.fixture
def create_run_queue():
    """Create a queue through wandb-core for legacy Launch test setup."""

    def _create(
        service_api: ServiceApi,
        *,
        entity: str,
        project: str,
        queue_name: str,
        access: str,
    ):
        response = service_api.send_api_request(
            ApiRequest(
                run_queue_operation_request=RunQueueOperationRequest(
                    create_run_queue_request=CreateRunQueueRequest(
                        entity=entity,
                        project=project,
                        queue_name=queue_name,
                        access=access,
                    )
                )
            )
        )
        return response.run_queue_operation_response.create_run_queue_response

    return _create
