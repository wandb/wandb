from __future__ import annotations

import atexit
import pathlib
from typing import Callable

from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_settings_pb2, wandb_sync_pb2
from wandb.sdk import wandb_settings
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.interface.interface_sock import InterfaceSock
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.exit_hooks import ExitHooks
from wandb.sdk.lib.service.service_client import ServiceClient
from wandb.sdk.mailbox import HandleAbandonedError, MailboxClosedError
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

from . import service_process, service_token


class WandbAttachFailedError(Exception):
    """Failed to attach to a run."""


def connect_to_service(
    asyncer: asyncio_manager.AsyncioManager,
    settings: wandb_settings.Settings,
) -> ServiceConnection:
    """Connect to the service process, starting one up if necessary."""
    token = service_token.from_env()

    if token:
        return ServiceConnection(
            asyncer=asyncer,
            client=token.connect(asyncer=asyncer),
            proc=None,
        )
    else:
        return _start_and_connect_service(asyncer, settings)


def _start_and_connect_service(
    asyncer: asyncio_manager.AsyncioManager,
    settings: wandb_settings.Settings,
) -> ServiceConnection:
    """Start a service process and returns a connection to it.

    An atexit hook is registered to tear down the service process and wait for
    it to complete. The hook does not run in processes started using the
    multiprocessing module.
    """
    proc = service_process.start(settings)

    client = proc.token.connect(asyncer=asyncer)
    proc.token.save_to_env()

    hooks = ExitHooks()
    hooks.hook()

    def teardown_atexit():
        conn.teardown(hooks.exit_code)

    conn = ServiceConnection(
        asyncer=asyncer,
        client=client,
        proc=proc,
        cleanup=lambda: atexit.unregister(teardown_atexit),
    )

    atexit.register(teardown_atexit)

    return conn


class ServiceConnection:
    """A connection to the W&B internal service process.

    None of the synchronous methods may be called in an asyncio context.
    """

    def __init__(
        self,
        asyncer: asyncio_manager.AsyncioManager,
        client: ServiceClient,
        proc: service_process.ServiceProcess | None,
        cleanup: Callable[[], None] | None = None,
    ):
        """Returns a new ServiceConnection.

        Args:
            asyncer: An asyncio runner.
            client: A client for communicating with the service over a socket.
            proc: The service process if we own it, or None otherwise.
            cleanup: A callback to run on teardown before doing anything.
        """
        self._asyncer = asyncer
        self._client = client
        self._proc = proc
        self._torn_down = False
        self._cleanup = cleanup

    def make_interface(self, stream_id: str) -> InterfaceBase:
        """Returns an interface for communicating with the service."""
        return InterfaceSock(
            self._asyncer,
            self._client,
            stream_id=stream_id,
        )

    async def init_sync(
        self,
        paths: set[pathlib.Path],
        settings: wandb_settings.Settings,
    ) -> MailboxHandle[wandb_sync_pb2.ServerInitSyncResponse]:
        """Send a ServerInitSyncRequest."""
        init_sync = wandb_sync_pb2.ServerInitSyncRequest(
            path=(str(path) for path in paths),
            settings=settings.to_proto(),
        )
        request = spb.ServerRequest(init_sync=init_sync)

        handle = await self._client.deliver(request)
        return handle.map(lambda r: r.init_sync_response)

    async def sync(
        self,
        id: str,
        *,
        parallelism: int,
    ) -> MailboxHandle[wandb_sync_pb2.ServerSyncResponse]:
        """Send a ServerSyncRequest."""
        sync = wandb_sync_pb2.ServerSyncRequest(id=id, parallelism=parallelism)
        request = spb.ServerRequest(sync=sync)

        handle = await self._client.deliver(request)
        return handle.map(lambda r: r.sync_response)

    async def sync_status(
        self,
        id: str,
    ) -> MailboxHandle[wandb_sync_pb2.ServerSyncStatusResponse]:
        """Send a ServerSyncStatusRequest."""
        sync_status = wandb_sync_pb2.ServerSyncStatusRequest(id=id)
        request = spb.ServerRequest(sync_status=sync_status)

        handle = await self._client.deliver(request)
        return handle.map(lambda r: r.sync_status_response)

    def inform_init(
        self,
        settings: wandb_settings_pb2.Settings,
        run_id: str,
    ) -> None:
        """Send an init request to the service."""
        request = spb.ServerInformInitRequest()
        request.settings.CopyFrom(settings)
        request._info.stream_id = run_id
        self._asyncer.run(
            lambda: self._client.publish(spb.ServerRequest(inform_init=request))
        )

    def inform_finish(self, run_id: str) -> None:
        """Send an finish request to the service."""
        request = spb.ServerInformFinishRequest()
        request._info.stream_id = run_id
        self._asyncer.run(
            lambda: self._client.publish(spb.ServerRequest(inform_finish=request))
        )

    def inform_attach(
        self,
        attach_id: str,
    ) -> wandb_settings_pb2.Settings:
        """Send an attach request to the service.

        Raises a WandbAttachFailedError if attaching is not possible.
        """
        request = spb.ServerRequest()
        request.inform_attach._info.stream_id = attach_id

        try:
            handle = self._asyncer.run(lambda: self._client.deliver(request))
            response = handle.wait_or(timeout=10)

        except (MailboxClosedError, HandleAbandonedError):
            raise WandbAttachFailedError(
                "Failed to attach: the service process is not running.",
            ) from None

        except TimeoutError:
            raise WandbAttachFailedError(
                "Failed to attach because the run does not belong to"
                " the current service process, or because the service"
                " process is busy (unlikely)."
            ) from None

        else:
            return response.inform_attach_response.settings

    def teardown(self, exit_code: int) -> int | None:
        """Close the connection.

        Stop reading responses on the connection, and if this connection owns
        the service process, send a teardown message and wait for it to shut
        down.

        This may only be called once.

        Returns:
            The exit code of the service process, or None if the process was
            not owned by this connection.
        """
        if self._torn_down:
            raise AssertionError("Already torn down.")
        self._torn_down = True

        if self._cleanup:
            self._cleanup()

        if not self._proc:
            return None

        # Clear the service token to prevent new connections to the process.
        service_token.clear_service_in_env()

        async def publish_teardown_and_close() -> None:
            await self._client.publish(
                spb.ServerRequest(
                    inform_teardown=spb.ServerInformTeardownRequest(
                        exit_code=exit_code,
                    )
                ),
            )
            await self._client.close()

        self._asyncer.run(publish_teardown_and_close)

        return self._proc.join()
