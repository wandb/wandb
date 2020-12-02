"""
module server
"""

import json
import os
import sys

from wandb import util
from wandb.errors.error import CommError
from wandb.apis import InternalApi


class ServerError(Exception):
    pass


def _is_kaggle() -> bool:
    return (
        os.getenv("KAGGLE_KERNEL_RUN_TYPE") is not None
        or "kaggle_environments" in sys.modules  # noqa: W503
    )


class Server(object):
    def __init__(self, api=None, settings=None):
        self._api = api or InternalApi(default_settings=settings)
        self._error_network = None
        self._viewer = {}
        self._flags = {}
        self._settings = settings

    def query_with_timeout(self, timeout=None):
        if self._settings and self._settings._disable_viewer:
            return
        timeout = timeout or 5
        async_viewer = util.async_call(self._api.viewer_server_info, timeout=timeout)
        try:
            viewer_tuple, viewer_thread = async_viewer()
        except Exception:
            # TODO: currently a bare exception as lots can happen, we should classify
            self._error_network = True
            return
        if viewer_thread.is_alive():
            if _is_kaggle():
                raise CommError(
                    "To use W&B in kaggle you must enable internet in the settings panel on the right."  # noqa: E501
                )
            # this is likely a DNS hang
            self._error_network = True
            return
        self._error_network = False
        # TODO(jhr): should we kill the thread?
        self._viewer, self._serverinfo = viewer_tuple
        self._flags = json.loads(self._viewer.get("flags", "{}"))

    def is_valid(self):
        if self._error_network is None:
            raise Exception("invalid usage: must query server")
        return self._error_network
