"""Manage wandb processes.

Create a manager channel.
"""

import atexit
import os
from typing import TYPE_CHECKING, Callable, Optional

import psutil

import wandb
from wandb import env, trigger
from wandb.errors import Error
from wandb.sdk.lib.exit_hooks import ExitHooks

if TYPE_CHECKING:
    from wandb.proto import wandb_settings_pb2
    from wandb.sdk.service import service
    from wandb.sdk.service.service_base import ServiceInterface
    from wandb.sdk.wandb_settings import Settings


class ManagerConnectionError(Error):
    """Raised when service process is not running."""

    pass


class ManagerConnectionRefusedError(ManagerConnectionError):
    """Raised when service process is not running."""

    pass


class _ManagerToken:
    _version = "2"
    _supported_transports = {"tcp"}
    _token_str: str
    _pid: int
    _transport: str
    _host: str
    _port: int

    def __init__(self, token: str) -> None:
        self._token_str = token
        self._parse()

    @classmethod
    def from_environment(cls) -> Optional["_ManagerToken"]:
        token = os.environ.get(env.SERVICE)
        if not token:
            return None
        return cls(token=token)

    @classmethod
    def from_params(cls, transport: str, host: str, port: int) -> "_ManagerToken":
        version = cls._version
        pid = os.getpid()
        token = "-".join([version, str(pid), transport, host, str(port)])
        return cls(token=token)

    def set_environment(self) -> None:
        os.environ[env.SERVICE] = self._token_str

    def _parse(self) -> None:
        assert self._token_str
        parts = self._token_str.split("-")
        assert len(parts) == 5, f"token must have 5 parts: {parts}"
        # TODO: make more robust?
        version, pid_str, transport, host, port_str = parts
        assert version == self._version
        assert transport in self._supported_transports
        self._pid = int(pid_str)
        self._transport = transport
        self._host = host
        self._port = int(port_str)

    def reset_environment(self) -> None:
        os.environ.pop(env.SERVICE, None)

    @property
    def token(self) -> str:
        return self._token_str

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def transport(self) -> str:
        return self._transport

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port


class _Manager:
    _token: _ManagerToken
    _atexit_lambda: Optional[Callable[[], None]]
    _hooks: Optional[ExitHooks]
    _settings: "Settings"
    _service: "service._Service"

    def _service_connect(self) -> None:
        port = self._token.port
        svc_iface = self._get_service_interface()

        try:
            svc_iface._svc_connect(port=port)

        except ConnectionRefusedError as e:
            if not psutil.pid_exists(self._token.pid):
                message = (
                    "Connection to wandb service failed"
                    " because the process is not available."
                )
            else:
                message = "Connection to wandb service failed."
            raise ManagerConnectionRefusedError(message) from e

        except Exception as e:
            raise ManagerConnectionError(
                "Connection to wandb service failed.",
            ) from e

    def __init__(self, settings: "Settings") -> None:
        """Connects to the internal service, starting it if necessary."""
        from wandb.sdk.service import service

        self._settings = settings
        self._atexit_lambda = None
        self._hooks = None

        self._service = service._Service(settings=self._settings)

        token = _ManagerToken.from_environment()
        if not token:
            self._service.start()
            host = "localhost"
            transport = "tcp"
            port = self._service.sock_port
            assert port
            token = _ManagerToken.from_params(transport=transport, host=host, port=port)
            token.set_environment()
            self._atexit_setup()
        self._token = token

        try:
            self._service_connect()
        except ManagerConnectionError as e:
            wandb._sentry.reraise(e)

    def _teardown(self, exit_code: int) -> int:
        """Shuts down the internal process and returns its exit code.

        This sends a teardown record to the process. An exception is raised if
        the process has already been shut down.
        """
        if self._atexit_lambda:
            atexit.unregister(self._atexit_lambda)
            self._atexit_lambda = None

        try:
            self._inform_teardown(exit_code)
            return self._service.join()
        finally:
            self._token.reset_environment()

    def _atexit_setup(self) -> None:
        self._atexit_lambda = lambda: self._atexit_teardown()

        self._hooks = ExitHooks()
        self._hooks.hook()
        atexit.register(self._atexit_lambda)

    def _atexit_teardown(self) -> None:
        trigger.call("on_finished")

        # Clear the atexit hook---we're executing it now, after which the
        # process will exit.
        self._atexit_lambda = None

        try:
            self._teardown(self._hooks.exit_code if self._hooks else 0)
        except Exception as e:
            wandb.termlog(
                f"Encountered an error while tearing down the service manager: {e}",
                repeat=False,
            )

    def _get_service(self) -> "service._Service":
        return self._service

    def _get_service_interface(self) -> "ServiceInterface":
        assert self._service
        svc_iface = self._service.service_interface
        assert svc_iface
        return svc_iface

    def _inform_init(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
        svc_iface = self._get_service_interface()
        svc_iface._svc_inform_init(settings=settings, run_id=run_id)

    def _inform_start(
        self, settings: "wandb_settings_pb2.Settings", run_id: str
    ) -> None:
        svc_iface = self._get_service_interface()
        svc_iface._svc_inform_start(settings=settings, run_id=run_id)

    def _inform_attach(self, attach_id: str) -> Optional["wandb_settings_pb2.Settings"]:
        svc_iface = self._get_service_interface()
        try:
            response = svc_iface._svc_inform_attach(attach_id=attach_id)
        except Exception:
            return None
        return response.settings

    def _inform_finish(self, run_id: Optional[str] = None) -> None:
        svc_iface = self._get_service_interface()
        svc_iface._svc_inform_finish(run_id=run_id)

    def _inform_teardown(self, exit_code: int) -> None:
        svc_iface = self._get_service_interface()
        svc_iface._svc_inform_teardown(exit_code)
