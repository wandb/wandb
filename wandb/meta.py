import json
import os
import sys
import platform
import multiprocessing
import pynvml
import threading
import time
import socket
import getpass
from datetime import datetime

from wandb import util
from wandb import env
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

    def start(self):
        self._thread.start()

    def setup(self):
        self.data["root"] = os.getcwd()
        if self._api.git.enabled:
            self.data["git"] = {
                "remote": self._api.git.remote_url,
                "commit": self._api.git.last_commit
            }
            self.data["email"] = self._api.git.email
            self.data["root"] = self._api.git.root or self.data["root"]

        self.data["startedAt"] = datetime.utcfromtimestamp(
            wandb.START_TIME).isoformat()
        self.data["host"] = socket.gethostname()
        try:
            username = getpass.getuser()
        except KeyError:
            # getuser() could raise KeyError in restricted environments like
            # chroot jails or docker containers.  Return user id in these cases.
            username = str(os.getuid())
        self.data["username"] = os.getenv("WANDB_USERNAME", username)
        self.data["os"] = platform.platform(aliased=True)
        self.data["python"] = platform.python_version()
        if env.get_docker():
            self.data["docker"] = env.get_docker()
        try:
            pynvml.nvmlInit()
            self.data["gpu"] = pynvml.nvmlDeviceGetName(
                pynvml.nvmlDeviceGetHandleByIndex(0)).decode("utf8")
            self.data["gpu_count"] = pynvml.nvmlDeviceGetCount()
        except pynvml.NVMLError:
            pass
        try:
            self.data["cpu_count"] = multiprocessing.cpu_count()
        except NotImplementedError:
            pass
        try:
            import __main__
            self.data["program"] = __main__.__file__
        except (ImportError, AttributeError):
            self.data["program"] = '<python with no main file>'
        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            self.data["cuda"] = open(
                "/usr/local/cuda/version.txt").read().split(" ")[-1].strip()
        self.data["args"] = sys.argv[1:]
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
        try:
            self._thread.join()
        # Incase we never start it
        except RuntimeError:
            pass

    def _thread_body(self):
        seconds = 0
        while True:
            if seconds > self.HEARTBEAT_INTERVAL_SECONDS or self._shutdown:
                self.write()
                seconds = 0
            if self._shutdown:
                break
            else:
                time.sleep(1)
                seconds += 1
