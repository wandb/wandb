import sys
import subprocess
import os
import atexit
import time
import grpc

import wandb
from wandb.internal.wandb_internal_client import WandbInternalClient


class Backend(object):
    def __init__(self, mode=None):
        self._process = None
        self._client = None

    def ensure_launched(self):
        """Launch backend worker if not running."""

        internal_server_path = os.path.join(
            os.path.dirname(__file__), 'wandb_internal_server.py')

        process = subprocess.Popen([sys.executable, internal_server_path])
        self._process = process
        atexit.register(lambda: self._atexit_cleanup())

    def server_connect(self):
        """Connect to server."""
        client = WandbInternalClient()
        time.sleep(0.5)

        connected = False
        for i in range(20):
            try:
                client.connect()
                client.status()
            except grpc.RpcError as e:
                print("connect retry", i)
                time.sleep((i + 1) * 0.1)
            else:
                connected = True
                break
        if not connected:
            print("not connected, bad")
            # TODO(jhr): handle this

        self._client = client

    def server_status(self):
        """Report server status."""
        pass

    def _atexit_cleanup(self):
        try:
            self._client.shutdown()
        except grpc.RpcError as e:
            print("shutdown error")
        self._process.kill()
        wandb.termlog("Cleanup: done")

    def log(self, data):
        self._client.log(data)
