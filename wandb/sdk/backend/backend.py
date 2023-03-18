"""Backend - Send to internal process.

Manage backend.

"""

import logging
import multiprocessing
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from ..interface.interface import InterfaceBase
from ..lib.mailbox import Mailbox
from ..wandb_manager import _Manager
from ..wandb_settings import Settings

if TYPE_CHECKING:
    from ..service.service_grpc import ServiceGrpcInterface
    from ..service.service_sock import ServiceSockInterface
    from ..wandb_run import Run


logger = logging.getLogger("wandb")


class Backend:
    # multiprocessing context or module
    _multiprocessing: multiprocessing.context.BaseContext
    interface: Optional[InterfaceBase]
    # _internal_pid: Optional[int]
    _settings: Optional[Settings]
    _mailbox: Mailbox

    def __init__(
        self,
        mailbox: Mailbox,
        settings: Optional[Settings] = None,
        log_level: Optional[int] = None,
        manager: Optional[_Manager] = None,
    ) -> None:
        self._done = False
        self.interface = None
        self._settings = settings
        self._log_level = log_level
        self._manager = manager
        self._mailbox = mailbox

        self._multiprocessing = multiprocessing  # type: ignore
        self._multiprocessing_setup()

    def _hack_set_run(self, run: "Run") -> None:
        assert self.interface
        self.interface._hack_set_run(run)

    def _multiprocessing_setup(self) -> None:
        assert self._settings
        if self._settings.start_method == "thread":
            return

        # defaulting to spawn for now, fork needs more testing
        start_method = self._settings.start_method or "spawn"

        # TODO: use fork context if unix and frozen?
        # if py34+, else fall back
        if not hasattr(multiprocessing, "get_context"):
            return
        all_methods = multiprocessing.get_all_start_methods()
        logger.info(
            "multiprocessing start_methods={}, using: {}".format(
                ",".join(all_methods), start_method
            )
        )
        ctx = multiprocessing.get_context(start_method)
        self._multiprocessing = ctx

    def _ensure_launched_manager(self) -> None:
        # grpc_port: Optional[int] = None
        # attach_id = self._settings._attach_id if self._settings else None
        # if attach_id:
        #     # TODO(attach): implement
        #     # already have a server, assume it is already up
        #     grpc_port = int(attach_id)

        assert self._manager
        svc = self._manager._get_service()
        assert svc
        svc_iface = svc.service_interface

        svc_transport = svc_iface.get_transport()
        if svc_transport == "tcp":
            from ..interface.interface_sock import InterfaceSock

            svc_iface_sock = cast("ServiceSockInterface", svc_iface)
            sock_client = svc_iface_sock._get_sock_client()
            sock_interface = InterfaceSock(sock_client, mailbox=self._mailbox)
            self.interface = sock_interface
        elif svc_transport == "grpc":
            from ..interface.interface_grpc import InterfaceGrpc

            svc_iface_grpc = cast("ServiceGrpcInterface", svc_iface)
            stub = svc_iface_grpc._get_stub()
            grpc_interface = InterfaceGrpc(mailbox=self._mailbox)
            grpc_interface._connect(stub=stub)
            self.interface = grpc_interface
        else:
            raise AssertionError(f"Unsupported service transport: {svc_transport}")

    def ensure_launched(self) -> None:
        """Launch backend worker if not running."""
        settings: Dict[str, Any] = dict()
        if self._settings is not None:
            settings = self._settings.make_static()

        settings["_log_level"] = self._log_level or logging.DEBUG

        # TODO: this is brittle and should likely be handled directly on the
        #  settings object. Multiprocessing blows up when it can't pickle
        #  objects.
        if "_early_logger" in settings:
            del settings["_early_logger"]

        self._ensure_launched_manager()

    def cleanup(self) -> None:
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        if self.interface:
            self.interface.join()
