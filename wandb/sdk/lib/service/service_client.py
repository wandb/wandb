from __future__ import annotations

import asyncio
import logging
import struct

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.mailbox.mailbox import Mailbox
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_logger = logging.getLogger(__name__)


class ServiceClient:
    """Implements socket communication with the internal service."""

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._asyncer = asyncer
        self._reader = reader
        self._writer = writer
        self._mailbox = Mailbox(asyncer)
        asyncer.run_soon(self._forward_responses, daemon=True)

    def publish(self, request: spb.ServerRequest) -> None:
        """Send a request without waiting for a response."""
        self._asyncer.run_soon(lambda: self._send_server_request(request))

    def deliver(
        self,
        request: spb.ServerRequest,
    ) -> MailboxHandle[spb.ServerResponse]:
        """Send a request and return a handle to wait for a response.

        NOTE: This may mutate the request. The request should not be used
        after.
        """
        handle = self._mailbox.require_response(request)
        self._asyncer.run_soon(lambda: self._send_server_request(request))
        return handle

    async def _send_server_request(self, request: spb.ServerRequest) -> None:
        header = struct.pack("<BI", ord("W"), request.ByteSize())
        self._writer.write(header)

        data = request.SerializeToString()
        self._writer.write(data)

        await self._writer.drain()

    def close(self) -> None:
        """Flush and close the socket."""
        self._asyncer.run_soon(self._close)

    async def _close(self) -> None:
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
            header = await self._reader.readexactly(5)
        except asyncio.IncompleteReadError as e:
            if e.partial:
                raise
            else:
                return None

        magic, length = struct.unpack("<BI", header)

        if magic != ord("W"):
            raise ValueError(f"Bad header: {header.hex()}")

        data = await self._reader.readexactly(length)
        response = spb.ServerResponse()
        response.ParseFromString(data)
        return response
