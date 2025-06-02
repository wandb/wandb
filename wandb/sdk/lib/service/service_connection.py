from __future__ import annotations

import atexit
from typing import Callable

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_server_pb2 as spb
from wandb.proto import wandb_settings_pb2
from wandb.sdk import wandb_settings
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.interface.interface_sock import InterfaceSock
from wandb.sdk.interface.router_sock import MessageSockRouter
from wandb.sdk.lib.exit_hooks import ExitHooks
from wandb.sdk.lib.sock_client import SockClient, SockClientClosedError
from wandb.sdk.mailbox import HandleAbandonedError, Mailbox, MailboxClosedError

from . import service_process, service_token


class WandbAttachFailedError(Exception):
    """Failed to attach to a run."""


def connect_to_service(
    settings: wandb_settings.Settings,
) -> ServiceConnection:
    """Connect to the service process, starting one up if necessary."""
    token = service_token.from_env()

    if token:
        return ServiceConnection(client=token.connect(), proc=None)
    else:
        return _start_and_connect_service(settings)


def _start_and_connect_service(
    settings: wandb_settings.Settings,
) -> ServiceConnection:
    """Start a service process and returns a connection to it.

    An atexit hook is registered to tear down the service process and wait for
    it to complete. The hook does not run in processes started using the
    multiprocessing module.
    """
    proc = service_process.start(settings)

    client = proc.token.connect()
    proc.token.save_to_env()

    hooks = ExitHooks()
    hooks.hook()

    def teardown_atexit():
        conn.teardown(hooks.exit_code)

    conn = ServiceConnection(
        client=client,
        proc=proc,
        cleanup=lambda: atexit.unregister(teardown_atexit),
    )

    atexit.register(teardown_atexit)

    return conn


class ServiceConnection:
    """A connection to the W&B internal service process."""

    def __init__(
        self,
        client: SockClient,
        proc: service_process.ServiceProcess | None,
        cleanup: Callable[[], None] | None = None,
    ):
        """Returns a new ServiceConnection.

        Args:
            mailbox: The mailbox to use for all communication over the socket.
            router: A handle to the thread that reads from the socket and
                updates the mailbox.
            client: A socket that's connected to the service.
            proc: The service process if we own it, or None otherwise.
            cleanup: A callback to run on teardown before doing anything.
        """
        self._client = client
        self._proc = proc
        self._torn_down = False
        self._cleanup = cleanup

        self._mailbox = Mailbox()
        self._router = MessageSockRouter(self._client, self._mailbox)

    def make_interface(self, stream_id: str) -> InterfaceBase:
        """Returns an interface for communicating with the service."""
        return InterfaceSock(self._client, self._mailbox, stream_id=stream_id)

    def send_record(self, record: pb.Record) -> None:
        """Send data to the service."""
        self._client.send_record_publish(record)

    def inform_init(
        self,
        settings: wandb_settings_pb2.Settings,
        run_id: str,
    ) -> None:
        """Send an init request to the service."""
        request = spb.ServerInformInitRequest()
        request.settings.CopyFrom(settings)
        request._info.stream_id = run_id
        self._client.send_server_request(spb.ServerRequest(inform_init=request))

    def inform_finish(self, run_id: str) -> None:
        """Send an finish request to the service."""
        request = spb.ServerInformFinishRequest()
        request._info.stream_id = run_id
        self._client.send_server_request(spb.ServerRequest(inform_finish=request))

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
            handle = self._mailbox.require_response(request)
            self._client.send_server_request(request)
            response = handle.wait_or(timeout=10)

        except (MailboxClosedError, HandleAbandonedError, SockClientClosedError):
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

    def inform_start(
        self,
        settings: wandb_settings_pb2.Settings,
        run_id: str,
    ) -> None:
        """Send a start request to the service."""
        request = spb.ServerInformStartRequest()
        request.settings.CopyFrom(settings)
        request._info.stream_id = run_id
        self._client.send_server_request(spb.ServerRequest(inform_start=request))

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

        # Stop reading responses on the socket.
        self._router.join()

        if not self._proc:
            return None

        # Clear the service token to prevent new connections to the process.
        service_token.clear_service_in_env()

        self._client.send_server_request(
            spb.ServerRequest(
                inform_teardown=spb.ServerInformTeardownRequest(
                    exit_code=exit_code,
                )
            ),
        )

        return self._proc.join()
