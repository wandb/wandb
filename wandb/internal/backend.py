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
        #print("started", self._process.pid)
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
            return

        # block signals since we will let the server handle them?
        # Dont think this is right
        #import signal
        #try:
        #    signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        #    signal.signal(signal.SIGTERM, signal.SIG_IGN)
        #    signal.signal(signal.SIGINT, signal.SIG_IGN)
        #except (AttributeError, ValueError):  # SIGQUIT doesn't exist on windows, we can't use signal.signal in threads for tests
        #    pass

        self._client = client

    def server_status(self):
        """Report server status."""
        pass

    def _grpc_shutdown(self):
        try:
            self._client.shutdown()
        except grpc.RpcError as e:
            print("shutdown error")

    def _atexit_cleanup(self):
        proc = self._process
        self._process = None
        if not proc:
            return
        #print("cleanup")

        # Give each attempt ~8 seconds 
        for stop_func in (self._grpc_shutdown, proc.terminate, proc.kill):
            stop_func()
            running = True
            for _ in range(80):
                r = proc.poll()
                if r is not None:
                    running = False
                    break
                time.sleep(0.1)
            if not running:
                break
        if running:
            wandb.termwarn("Cleanup: problem killing")
            # TODO(jhr): anything else to do here?

    def join(self):
        self._atexit_cleanup()

    def log(self, data):
        self._client.log(data)

    def run_update(self, data):
        self._client.run_update(data)

