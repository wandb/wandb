#
"""
pytorch profiler
"""
import os
import time
import threading
import glob
from typing import TYPE_CHECKING
import wandb
from . import tb_watcher

if TYPE_CHECKING:
    from typing import Dict, List, Optional
    from ..interface.interface import BackendSender
    from .settings_static import SettingsStatic

PYTORCH_PROFILER_MODULE = "torch.profiler"
POLLING_INTERVAL = 5


def trace_handler(
    logdir: str, worker_name: "Optional[str]" = None, use_gzip: bool = False
):
    torch_profiler = wandb.util.get_module(PYTORCH_PROFILER_MODULE)
    _notify_tensorboard_logdir(logdir, log_type="profiler")
    return torch_profiler.tensorboard_trace_handler(logdir, worker_name, use_gzip)


def _notify_tensorboard_logdir(logdir, save=None, root_logdir=None, log_type=None):
    wandb.run._tensorboard_callback(
        logdir, save=save, root_logdir=root_logdir, log_type=log_type
    )


class ProfilerWatcher(object):
    def __init__(self, interface: "BackendSender", settings: "SettingsStatic"):
        self._logdir = None
        self._interface = interface
        self._settings = settings
        self._thread = threading.Thread(target=self._thread_body)
        self._shutdown = threading.Event()
        self._seen = set()

    def start(self) -> None:
        self._thread.start()

    def add(self, logdir: str):
        self._logdir = logdir

    def _thread_body(self) -> None:
        while True:
            files = glob.glob(os.path.join(self._logdir, "*trace.json"))
            if len(files) > len(self._seen):
                new_files = set(files) - self._seen
                for path in new_files:
                    self._seen.add(path)
                    tb_watcher._link_and_save_file(
                        path=path,
                        base_path=os.path.dirname(path),
                        interface=self._interface,
                        settings=self._settings,
                    )
            if self._shutdown.is_set():
                break
            time.sleep(POLLING_INTERVAL)

    def finish(self) -> None:
        self._shutdown.set()
        self._thread.join()
