"""Allows Python garbage collection to trigger wandb-core cleanup.

This is tricky to implement correctly and requires a good understanding of
Python's garbage collection and every line in this file. If done wrong, it can
cause random deadlocks, and it has in the past. Even if done correctly, it may
still not work depending on the internals of the Python implementation.

This implementation relies on the SimpleQueue class, whose CPython
implementation is reentrant, though this is not well documented.
No guarantees are made about other Pythons.

It is strongly recommended to avoid designs that rely on this.
Prefer to create stateless APIs or use explicit resource management instead.
"""

from __future__ import annotations

import functools
import queue
import threading
import weakref
from collections.abc import Callable

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service.service_client import ServiceClient


class ServiceFinalizer:
    """Publishes cleanup requests in a daemon thread.

    Cleanup requests are not guaranteed to be published, in particular when the
    process exits.

    Thread-safe, but not reentrant (so its methods cannot be called inside
    a finalizer, just like most classes).
    """

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        client: ServiceClient,
    ) -> None:
        self._asyncer = asyncer
        self._client = client

        self._queue = queue.SimpleQueue[spb.ServerRequest | None]()
        self._thread = threading.Thread(
            name="wandb-ServiceFinalizer",
            target=self._publish_queue,
            # Daemon because we cannot guarantee that close() is called
            # before the process exits, so the thread must not block the
            # process from exiting. This also means that cleanup requests
            # are not sent at process exit.
            daemon=True,
        )
        self._thread.start()

    def finalize(
        self,
        obj: object,
        cleanup: spb.ServerRequest,
    ) -> Callable[[], None]:
        """Publish the cleanup request when the object is garbage collected.

        The request must not hold a reference to the object, or else the
        finalizer will never run.

        Safe to call after `close()`. Cleanup requests for objects that are
        garbage collected after `close()` are ignored.

        Returns:
            A callable finalizer object that can be used to submit the cleanup
            request (to a queue) immediately. Invoking this after `close()`
            does nothing. Calls after the first one do nothing.
        """
        # If the object is garbage collected after close(), its request will
        # be added to the queue and ignored. This finalizer prevents the
        # SimpleQueue (and any requests in it) from being garbage collected.
        #
        # SimpleQueue's `put` is designed to be safe to call in a finalizer,
        # at least in CPython.
        return weakref.finalize(obj, self._queue.put, cleanup)

    def close(self) -> None:
        """Flush all cleanup requests and join the thread.

        Safe to call multiple times.
        """
        self._queue.put(None)
        self._thread.join()

    def _publish_queue(self) -> None:
        """Publish requests in _queue until a None value or an error."""
        while request := self._queue.get():
            self._asyncer.run(functools.partial(self._client.publish, request))
