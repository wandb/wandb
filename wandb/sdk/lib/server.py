"""module server."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from wandb import util
from wandb.apis import InternalApi

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


class Server:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self._api = InternalApi(default_settings=settings)
        self._viewer: dict[str, Any] = {}
        self._flags: dict[str, Any] = {}
        self._settings: Settings = settings

    def query_with_timeout(self, timeout: int | float = 5) -> None:
        if self._settings.x_disable_viewer:
            return
        async_viewer = util.async_call(self._api.viewer_server_info, timeout=timeout)
        try:
            viewer_tuple, viewer_thread = async_viewer()
        except Exception:
            return
        if viewer_thread.is_alive():
            # this is likely a DNS hang
            return
        # TODO(jhr): should we kill the thread?
        self._viewer, self._serverinfo = viewer_tuple
        self._flags = json.loads(self._viewer.get("flags", "{}"))
