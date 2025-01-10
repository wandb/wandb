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

    @property
    def viewer(self) -> dict[str, Any]:
        """
        Returns the viewer information queried from the backend `viewer` GraphQL API.

        The viewer contains information about the currently authenticated user, including:
        see the GraphQL viewer query defined here:
        https://github.com/wandb/wandb/blob/main/wandb/sdk/internal/internal_api.py#L948-L966

        Returns:
            dict: The viewer information dictionary, or empty dict if unavailable
        """
        if not self._viewer and not self._settings._offline:
            self.query_with_timeout()

        return self._viewer
