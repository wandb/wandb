from __future__ import annotations

import asyncio
import struct
import threading

import pytest
from typing_extensions import Literal
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk import mailbox
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service.service_client import ServiceClient


class _FakeServer:
    """A fake server to help test the client."""

    def __init__(self, asyncer: asyncio_manager.AsyncioManager) -> None:
        self.port = 0
        """The localhost port for the server, assigned by the fixture."""

        self._asyncer = asyncer

        # Initialized when first used. Buffer of 1.
        self._responses: (
            asyncio.Queue[spb.ServerResponse | bytes | Literal["stop"]] | None
        ) = None

        self._requests: list[spb.ServerRequest] = []
        self._done = threading.Event()

    async def respond(self, response: spb.ServerResponse | bytes) -> None:
        """Set the response for the current request."""
        if not self._responses:
            self._responses = asyncio.Queue(1)
        self._responses.put_nowait(response)

    async def close_connection(self) -> None:
        """Close the connection instead of responding to the current request."""
        if not self._responses:
            self._responses = asyncio.Queue(1)
        self._responses.put_nowait("stop")

    def requests(self) -> list[spb.ServerRequest]:
        """Block until all requests are received, then return them."""
        self._done.wait()
        return self._requests

    async def do_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Collect requests and send responses for one connection."""
        try:
            await self._impl_connection(reader, writer)
        finally:
            self._done.set()

    async def _impl_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        while True:
            try:
                header = await reader.readexactly(5)
            except asyncio.IncompleteReadError:
                break

            _, length = struct.unpack("<BI", header)
            data = await reader.readexactly(length)

            request = spb.ServerRequest()
            request.ParseFromString(data)
            self._requests.append(request)

            if request.request_id:
                if not self._responses:
                    self._responses = asyncio.Queue(1)
                response = await self._responses.get()

                if response == "stop":
                    break
                else:
                    await self._respond(request, response, writer)

        writer.close()
        await writer.wait_closed()

    async def _respond(
        self,
        request: spb.ServerRequest,
        response: spb.ServerResponse | bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Respond to a request with a given response."""
        if isinstance(response, spb.ServerResponse):
            response.request_id = request.request_id
            writer.write(struct.pack("<BI", ord("W"), response.ByteSize()))
            writer.write(response.SerializeToString())
        else:
            writer.write(response)

        await writer.drain()


@pytest.fixture
def asyncer():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        yield asyncer
    finally:
        asyncer.join()


@pytest.fixture
def fake_server(asyncer: asyncio_manager.AsyncioManager):
    spy = _FakeServer(asyncer)

    server = asyncer.run(lambda: asyncio.start_server(spy.do_connection, "localhost"))
    spy.port = server.sockets[0].getsockname()[1]

    asyncer.run_soon(server.serve_forever)

    try:
        yield spy
    finally:

        async def close_server():
            server.close()
            await server.wait_closed()

        asyncer.run(close_server)


@pytest.fixture
def client(
    asyncer: asyncio_manager.AsyncioManager,
    fake_server: _FakeServer,
) -> ServiceClient:
    """An initialized ServiceClient connected to the fake_server.

    Not automatically closed.
    """
    reader, writer = asyncer.run(
        lambda: asyncio.open_connection("localhost", fake_server.port),
    )
    return ServiceClient(asyncer, reader, writer)


def test_publish_sends_request(client: ServiceClient, fake_server: _FakeServer):
    try:
        request = spb.ServerRequest()
        request.record_publish.exit.exit_code = 123
        client.publish(request)
    finally:
        client.close()

    assert fake_server.requests() == [request]


def test_deliver_reads_response(
    asyncer: asyncio_manager.AsyncioManager,
    client: ServiceClient,
    fake_server: _FakeServer,
):
    expected_response = spb.ServerResponse()
    expected_response.result_communicate.run_result.error.message = "test"

    try:
        request = spb.ServerRequest()
        handle = client.deliver(request)
        asyncer.run(lambda: fake_server.respond(expected_response))

        response = handle.wait_or(timeout=5)
    finally:
        client.close()

    expected_response.request_id = request.request_id
    assert response == expected_response


def test_closes_mailbox_on_read_error(
    asyncer: asyncio_manager.AsyncioManager,
    client: ServiceClient,
    fake_server: _FakeServer,
):
    try:
        handle = client.deliver(spb.ServerRequest())
        asyncer.run(lambda: fake_server.respond(b"invalid response"))

        with pytest.raises(mailbox.HandleAbandonedError):
            handle.wait_or(timeout=5)
    finally:
        client.close()


def test_closes_mailbox_on_eof(
    asyncer: asyncio_manager.AsyncioManager,
    client: ServiceClient,
    fake_server: _FakeServer,
):
    try:
        handle = client.deliver(spb.ServerRequest())
        asyncer.run(fake_server.close_connection)

        with pytest.raises(mailbox.HandleAbandonedError):
            handle.wait_or(timeout=5)
    finally:
        client.close()
