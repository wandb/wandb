"""Backend - Send to internal process.

Manage backend.

"""

import logging
from typing import TYPE_CHECKING, Optional

from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.wandb_settings import Settings

if TYPE_CHECKING:
    from wandb.sdk.lib.service import service_connection

logger = logging.getLogger("wandb")


class Backend:
    interface: Optional[InterfaceBase]

    _settings: Settings

    _done: bool

    _service: Optional["service_connection.ServiceConnection"]

    def __init__(
        self,
        settings: Settings,
        service: Optional["service_connection.ServiceConnection"] = None,
    ) -> None:
        self._done = False

        self.interface = None

        self._settings = settings
        self._service = service

    def ensure_launched(self) -> None:
        """Launch backend worker if not running."""
        assert self._settings.run_id
        assert self._service
        self.interface = self._service.make_interface(
            stream_id=self._settings.run_id,
        )

    def server_status(self) -> None:
        """Report server status."""

    def cleanup(self) -> None:
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        if self.interface:
            self.interface.join()
