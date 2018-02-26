import json
import os
import threading
import time
import socket
import getpass
from datetime import datetime

from wandb import util
import wandb

METADATA_FNAME = 'wandb-metadata.json'


class Meta(object):
    """Used to store metadata during and after a run."""

    HEARTBEAT_INTERVAL_SECONDS = 15

    def __init__(self, api, out_dir='.'):
        self.fname = os.path.join(out_dir, METADATA_FNAME)
        self._api = api
        self._shutdown = False
        try:
            self.data = json.load(open(self.fname))
        except (IOError, ValueError):
            self.data = {}
        self.lock = threading.Lock()
        self.setup()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def setup(self):
        if self._api.git.enabled:
            self.data["git"] = {
                "remote": self._api.git.remote_url,
                "commit": self._api.git.last_commit
            }
        self.data["startedAt"] = datetime.utcfromtimestamp(
            wandb.START_TIME).isoformat()
        self.data["email"] = self._api.git.email
        self.data["root"] = self._api.git.root or os.getcwd()
        self.data["host"] = socket.gethostname()
        self.data["username"] = os.getenv("WANDB_USERNAME", getpass.getuser())
        try:
            import __main__
            self.data["program"] = __main__.__file__
        except (ImportError, AttributeError):
            self.data["program"] = '<python with no main file>'
        self.data["state"] = "running"
        self.write()

    def write(self):
        self.lock.acquire()
        try:
            self.data["heartbeatAt"] = datetime.utcnow().isoformat()
            with open(self.fname, 'w') as f:
                s = util.json_dumps_safer(self.data, indent=4)
                f.write(s)
                f.write('\n')
        finally:
            self.lock.release()

    def shutdown(self):
        self._shutdown = True
        self._thread.join()

    def _thread_body(self):
        seconds = 0
        while True:
            if seconds > self.HEARTBEAT_INTERVAL_SECONDS or self._shutdown:
                self.write()
                seconds = 0
            if self._shutdown:
                break
            else:
                time.sleep(2)
                seconds += 2
