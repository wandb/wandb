"""
module server
"""

import json

from wandb import util
from wandb.apis import InternalApi


class ServerError(Exception):
    pass


class Server(object):
    def __init__(self, api=None):
        self._api = api or InternalApi()
        self._error_network = None
        self._viewer = None
        self._flags = None

    def query_with_timeout(self, timeout=None):
        timeout = timeout or 5
        async_viewer = util.async_call(self._api.viewer, timeout=timeout)
        viewer, viewer_thread = async_viewer()
        if viewer_thread.is_alive():
            self._error_network = True
            return
        self._error_network = False
        # TODO(jhr): should we kill the thread?
        self._viewer = viewer
        self._flags = json.loads(viewer.get("flags", "{}"))

    def is_valid(self):
        if self._error_network is None:
            raise Exception("invalid usage: must query server")
        return self._error_network
