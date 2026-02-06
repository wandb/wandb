from __future__ import annotations

import asyncio
import logging
import struct
import sys
from types import TracebackType

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.mailbox.mailbox import Mailbox
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_logger = logging.getLogger(__name__)

_HEADER_BYTE_INT_LEN = 5
_HEADER_BYTE_INT_FMT = "<BI"


class ServiceClient:
    """Implements socket communication with the internal service."""

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._broken_exc: Exception | None = None
        self._broken_tb: TracebackType | None = None

        self._drain_lock: asyncio.Lock | None = None

        self._reader = reader
        self._writer = writer
        self._mailbox = Mailbox(asyncer, self._cancel_request)
        asyncer.run_soon(
            self._forward_responses,
            daemon=True,
            name="ServiceClient._forward_responses",
        )

    async def publish(self, request: spb.ServerRequest) -> None:
        """Send a request without waiting for a response."""
        await self._send_server_request(request)

    async def deliver(
        self,
        request: spb.ServerRequest,
    ) -> MailboxHandle[spb.ServerResponse]:
        """Send a request and return a handle to wait for a response.

        NOTE: This may mutate the request. The request should not be used
        after.

        Raises:
            MailboxClosedError: If used after the client is closed or has
                stopped due to an error.
        """
        handle = self._mailbox.require_response(request)
        await self._send_server_request(request)
        return handle

    async def _send_server_request(self, request: spb.ServerRequest) -> None:
        if self._broken_exc:
            # Use with_traceback() to reuse the original traceback.
            # The exception's __traceback__ is modified by every `raise`
            # statement, so we must reset it to the original value.
            # The caller will receive an exception whose traceback has this
            # `raise` statement, followed by the `await self._writer.drain()`
            # statement, followed by the traceback there.
            #
            # We do this because `StreamWriter` stores an exception and doesn't
            # correctly reset the traceback when reraising (at least in older
            # Python versions).
            #
            # See https://bugs.python.org/issue45924.
            raise self._broken_exc.with_traceback(self._broken_tb)

        header = struct.pack(_HEADER_BYTE_INT_FMT, ord("W"), request.ByteSize())
        self._writer.write(header)

        data = request.SerializeToString()
        self._writer.write(data)

        try:
            await self._drain_writer()
        except Exception as e:
            self._broken_exc = e
            self._broken_tb = e.__traceback__
            raise

    async def _drain_writer(self) -> None:
        """Wait for the socket's flow control."""
        if sys.version_info >= (3, 10):
            await self._writer.drain()
            return

        # Prior to 3.10, drain() incorrectly raised an AssertionError when the
        # write buffer was maxed out if called from more than one async task.

        self._drain_lock = self._drain_lock or asyncio.Lock()
        async with self._drain_lock:
            await self._writer.drain()

    async def _cancel_request(self, id: str, /) -> None:
        """Cancel a request by ID.

        Args:
            id: The request_id of a previously-sent ServerRequest.
        """
        await self.publish(
            spb.ServerRequest(
                cancel=spb.ServerCancelRequest(
                    request_id=id,
                )
            )
        )

    async def close(self) -> None:
        """Flush and close the socket."""
        self._writer.close()
        await self._writer.wait_closed()

    async def _forward_responses(self) -> None:
        try:
            while response := await self._read_server_response():
                await self._mailbox.deliver(response)

        except Exception:
            _logger.exception("Error reading server response.")

        else:
            _logger.info("Reached EOF.")

        finally:
            self._mailbox.close()

    async def _read_server_response(self) -> spb.ServerResponse | None:
        try:
            header = await self._reader.readexactly(_HEADER_BYTE_INT_LEN)
        except asyncio.IncompleteReadError as e:
            if e.partial:
                raise
            else:
                return None

        magic, length = struct.unpack(_HEADER_BYTE_INT_FMT, header)

        if magic != ord("W"):
            raise ValueError(f"Bad header: {header.hex()}")

        data = await self._reader.readexactly(length)
        response = spb.ServerResponse()
        response.ParseFromString(data)
        return response
