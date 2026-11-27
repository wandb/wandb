from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service.service_finalizer import ServiceFinalizer


@pytest.fixture(scope="module")
def asyncer() -> Generator[asyncio_manager.AsyncioManager]:
    manager = asyncio_manager.AsyncioManager()
    manager.start()

    try:
        yield manager
    finally:
        manager.join()


class SimpleObject:
    """A basic object that can be finalized.

    Python does not allow registering a finalizer for a plain `object()`.
    """


def test_service_finalizer_publishes(asyncer: asyncio_manager.AsyncioManager):
    mock_client = AsyncMock()
    service_finalizer = ServiceFinalizer(asyncer, mock_client)
    obj = SimpleObject()
    request = spb.ServerRequest(request_id="test-request")

    service_finalizer.finalize(obj, request)
    del obj  # Should finalize synchronously.
    service_finalizer.close()

    mock_client.publish.assert_awaited_once_with(request)
