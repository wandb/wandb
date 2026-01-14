import threading
import unittest.mock

import pytest
from wandb.sdk.lib import asyncio_manager


class _TestError(Exception):
    """Intentional error raised in a test."""


async def _return_value(value: str) -> str:
    return value


async def _raise_test_error() -> None:
    raise _TestError


def test_run_returns_result():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        result = asyncer.run(lambda: _return_value("test result"))
    finally:
        asyncer.join()

    assert result == "test result"


def test_run_bubbles_exception():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        with pytest.raises(_TestError):
            asyncer.run(_raise_test_error)
    finally:
        asyncer.join()


def test_run__during_run__fails():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    async def something():
        pass

    async def run_something():
        asyncer.run(something)

    try:
        with pytest.raises(ValueError, match="inside async loop"):
            asyncer.run(run_something)
    finally:
        asyncer.join()


def test_run_soon__during_run__ok():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    it_worked = threading.Event()

    async def set_it_worked():
        it_worked.set()

    async def run_soon_set_it_worked():
        asyncer.run_soon(set_it_worked)

    try:
        asyncer.run(run_soon_set_it_worked)
        assert it_worked.wait(5)
    finally:
        asyncer.join()


def test_run_soon__exception__intercepted(monkeypatch):
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    mock_logger = unittest.mock.Mock()
    monkeypatch.setattr(asyncio_manager, "_logger", mock_logger)

    try:
        asyncer.run_soon(_raise_test_error)
    finally:
        asyncer.join()

    mock_logger.exception.assert_called_once_with(
        "Uncaught exception in run_soon callback.",
    )


def test_run_after_join_fails():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    asyncer.join()

    with pytest.raises(asyncio_manager.AlreadyJoinedError):
        asyncer.run(lambda: _return_value("test"))


def test_join_after_join_ok():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    asyncer.join()

    # Must not fail.
    asyncer.join()
