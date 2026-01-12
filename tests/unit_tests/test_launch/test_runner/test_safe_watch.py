from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client import ApiException
from urllib3.exceptions import ProtocolError
from wandb.sdk.launch.runner.kubernetes_monitor import SafeWatch


class MockWatch:
    """Mock class for testing."""

    def __init__(self):
        self.is_alive = True
        self.args = []
        self.queue = []

    async def stream(self, *args, **kwargs):
        """Simulate an input stream."""
        self.args.append((args, kwargs))
        while True:
            if not self.is_alive:
                break

            if not self.queue:
                continue

            item = self.queue.pop(0)

            if isinstance(item, Exception) or item is StopIteration:
                raise item

            yield item

    def stop(self):
        self.is_alive = False

    def add(self, item):
        self.queue.append(item)


def event_factory(resource_version):
    """Create an event."""
    mock_event = MagicMock()
    mock_event.get.return_value.metadata.resource_version = resource_version
    return mock_event


# If this timeout fails it means that the SafeWatch is not breaking out of its
# loop after stop() is called.
@pytest.mark.timeout(60)
@pytest.mark.asyncio
@pytest.mark.xfail(reason="This test is flaky.")
async def test_safe_watch():
    """Test that safewatch wraps properly.

    This unit test is designed to verify that the SafeWatch is properly wrapping
    the watch object so that it continues to yield items even if the watch object
    raises specific exceptions.
    """
    watch = MockWatch()

    item_1 = event_factory("1")
    item_2 = event_factory("2")
    item_3 = event_factory("3")
    item_4 = event_factory("4")

    watch.add(item_1)
    watch.add(ProtocolError("test"))
    watch.add(item_2)
    watch.add(StopIteration)
    watch.add(item_3)
    watch.add(ApiException(410))
    watch.add(item_4)

    safe_watch = SafeWatch(watch)
    stream = safe_watch.stream(None)
    assert await stream.__anext__() == item_1
    assert safe_watch._last_seen_resource_version == "1"
    assert await stream.__anext__() == item_2
    assert safe_watch._last_seen_resource_version == "2"
    assert await stream.__anext__() == item_3
    assert safe_watch._last_seen_resource_version == "3"
    assert await stream.__anext__() == item_4
    assert safe_watch._last_seen_resource_version == "4"
