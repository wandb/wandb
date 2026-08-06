import pytest
from wandb.apis.public.service_api import ServiceApi
from wandb.cli import cli
from wandb.proto.wandb_api_pb2 import (
    ApiRequest,
    CreateRunQueueRequest,
    RunQueueOperationRequest,
)


@pytest.fixture(autouse=True)
def _clear_cli_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset cli._api before each test.

    CliRunner invokes CLI commands in-process, so the module-level cache at
    cli._api survives across tests. A real CLI invocation gets a fresh
    process (and a fresh InternalApi); the autouse fixture mimics that so
    one test's cached client can't be reused by the next with a service
    connection that has since been torn down.
    """
    monkeypatch.setattr(cli, "_api", None)


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
