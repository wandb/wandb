import json
import os
import sys
import platform
import multiprocessing
import pynvml
import threading
import signal
import time
import socket
import getpass
import logging
from shutil import copyfile
from datetime import datetime

from wandb import util
from wandb import env
import wandb

METADATA_FNAME = 'wandb-metadata.json'

logger = logging.getLogger(__name__)


class Meta(object):
    """Used to store metadata during and after a run."""

    HEARTBEAT_INTERVAL_SECONDS = 15

    def __init__(self, api, out_dir='.'):
        self.out_dir = out_dir
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

    def _setup_code_git(self):
        if self._api.git.enabled:
            logger.debug("probe for git information")
            self.data["git"] = {
                "remote": self._api.git.remote_url,
                "commit": self._api.git.last_commit
            }
            self.data["email"] = self._api.git.email
            self.data["root"] = self._api.git.root or self.data["root"]

    def _setup_code_program(self):
        logger.debug("save program starting")
        program = os.path.join(self.data["root"], os.path.relpath(os.getcwd(), start=self.data["root"]), self.data["program"])
        logger.debug("save program starting: {}".format(program))
        if os.path.exists(program):
            relative_path = os.path.relpath(program, start=self.data["root"])
            # Ignore paths outside of out_dir when using custom dir
            if "../" in relative_path:
                relative_path = os.path.basename(relative_path)
            util.mkdir_exists_ok(os.path.join(self.out_dir, "code", os.path.dirname(relative_path)))
            saved_program = os.path.join(self.out_dir, "code", relative_path)
            logger.debug("save program saved: {}".format(saved_program))
            if not os.path.exists(saved_program):
                logger.debug("save program")
                copyfile(program, saved_program)
                self.data["codePath"] = relative_path

    def setup(self):
        class TimeOutException(Exception):
            pass
        def alarm_handler(signum, frame):
            raise TimeOutException()

        self.data["root"] = os.getcwd()
        program = os.getenv(env.PROGRAM) or util.get_program()
        if program and program != '<python with no main file>':
            self.data["program"] = program
        else:
            self.data["program"] = '<python with no main file>'
            if wandb._get_python_type() != "python":
                if os.getenv(env.NOTEBOOK_NAME):
                    self.data["program"] = os.getenv(env.NOTEBOOK_NAME)
                else:
                    meta = wandb.jupyter.notebook_metadata()
                    if meta.get("path"):
                        if "fileId=" in meta["path"]:
                            self.data["colab"] = "https://colab.research.google.com/drive/"+meta["path"].split("fileId=")[1]
                            self.data["program"] = meta["name"]
                        else:
                            self.data["program"] = meta["path"]
                            self.data["root"] = meta["root"]

        # Always save git information unless code saving is completely disabled
        if not os.getenv(env.DISABLE_CODE):
            self._setup_code_git()

        if env.should_save_code():
            logger.debug("code probe starting")
            in_jupyter = wandb._get_python_type() != "python"
            # windows doesn't support alarm() and jupyter could call this in a thread context
            if platform.system() == "Windows" or not hasattr(signal, 'SIGALRM') or in_jupyter:
                logger.debug("non time limited probe of code")
                self._setup_code_program()
            else:
                old_alarm = None
                try:
                    try:
                        old_alarm = signal.signal(signal.SIGALRM, alarm_handler)
                        signal.alarm(25)
                        self._setup_code_program()
                    finally:
                        signal.alarm(0)
                except TimeOutException:
                    logger.debug("timeout waiting for setup_code")
                finally:
                    if old_alarm:
                        signal.signal(signal.SIGALRM, old_alarm)
            logger.debug("code probe done")

        self.data["startedAt"] = datetime.utcfromtimestamp(wandb.START_TIME).isoformat()
        try:
            username = getpass.getuser()
        except KeyError:
            # getuser() could raise KeyError in restricted environments like
            # chroot jails or docker containers.  Return user id in these cases.
            username = str(os.getuid())

        # Host names, usernames, emails, the root directory, and executable paths are sensitive for anonymous users.
        if self._api.settings().get('anonymous') != 'true':
            self.data["host"] = os.environ.get(env.HOST, socket.gethostname())
            self.data["username"] = os.getenv(env.USERNAME, username)
            self.data["executable"] = sys.executable
        else:
            self.data.pop("email", None)
            self.data.pop("root", None)

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
        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            with open("/usr/local/cuda/version.txt") as f:
                self.data["cuda"] = f.read().split(" ")[-1].strip()
        self.data["args"] = sys.argv[1:]
        self.data["state"] = "running"

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
        # In case we never start it
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
