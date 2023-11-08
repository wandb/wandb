"""Backend - Send to internal process.

Manage backend.

"""

import logging
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from wandb.sdk.interface.interface import InterfaceBase
    from wandb.sdk.lib.mailbox import Mailbox
    from wandb.sdk.wandb_manager import _Manager
    from wandb.sdk.wandb_settings import Settings

    from ..service.service_sock import ServiceSockInterface
    from ..wandb_run import Run


logger = logging.getLogger("wandb")


class Backend:
    interface: Optional["InterfaceBase"]
    _settings: Optional["Settings"]
    _mailbox: "Mailbox"

    def __init__(
        self,
        mailbox: "Mailbox",
        settings: Optional["Settings"] = None,
        log_level: Optional[int] = None,
        manager: Optional["_Manager"] = None,
    ) -> None:
        self._done = False
        self.interface = None
        self._settings = settings
        self._log_level = log_level
        self._manager = manager
        self._mailbox = mailbox

    def _hack_set_run(self, run: "Run") -> None:
        assert self.interface
        self.interface._hack_set_run(run)

    def _ensure_launched_manager(self) -> None:
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
        else:
            raise AssertionError(f"Unsupported service transport: {svc_transport}")

    def ensure_launched(self) -> None:
        """Launch backend worker if not running."""
        if self._manager:
            self._ensure_launched_manager()
            return

    def server_status(self) -> None:
        """Report server status."""
        pass

    def cleanup(self) -> None:
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        if self.interface:
            self.interface.join()
        # No printing allowed from here until redirect restore!!!
