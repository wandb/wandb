from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import service_connection


@pytest.fixture(autouse=True)
def stub_finalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the connection from starting a finalizer thread."""
    monkeypatch.setattr(service_connection, "ServiceFinalizer", MagicMock())


def make_connection(
    asyncer: MagicMock,
    proc: MagicMock,
) -> service_connection.ServiceConnection:
    return service_connection.ServiceConnection(
        asyncer=asyncer,
        client=MagicMock(),
        proc=proc,
    )


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("the service process is gone"),
        asyncio_manager.ForkedError("this is a forked process"),
    ],
)
def test_teardown_does_not_raise_if_publish_fails(error: Exception):
    asyncer = MagicMock()
    asyncer.run.side_effect = error
    proc = MagicMock()

    exit_code = make_connection(asyncer, proc).teardown(0)

    assert exit_code is None
    proc.kill.assert_not_called()
    proc.join.assert_not_called()


def test_teardown_returns_service_exit_code():
    asyncer = MagicMock()
    proc = MagicMock()
    proc.join.return_value = 3

    assert make_connection(asyncer, proc).teardown(0) == 3
