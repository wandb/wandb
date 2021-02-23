#
# -*- coding: utf-8 -*-
"""Backend - Send to internal process

Manage backend.

"""

import logging
import multiprocessing
import os
import sys
import threading

import wandb

from ..interface import interface
from ..internal.internal import wandb_internal

logger = logging.getLogger("wandb")


class BackendThread(threading.Thread):
    """Class to running internal process as a thread."""

    def __init__(self, target, kwargs) -> None:
        threading.Thread.__init__(self)
        self._target = target
        self._kwargs = kwargs
        self.daemon = True
        self.pid = 0

    def run(self):
        self._target(**self._kwargs)


class Backend(object):
    # multiprocessing context or module
    _multiprocessing: object

    def __init__(self, settings=None, log_level=None):
        self._done = False
        self.record_q = None
        self.result_q = None
        self.wandb_process = None
        self.interface = None
        self._internal_pid = None
        self._settings = settings
        self._log_level = log_level

        self._multiprocessing = multiprocessing
        self._multiprocessing_setup()

    def _hack_set_run(self, run):
        self.interface._hack_set_run(run)

    def _multiprocessing_setup(self):
        if self._settings.start_method == "thread":
            return

        # defaulting to spawn for now, fork needs more testing
        start_method = self._settings.start_method or "spawn"

        # TODO: use fork context if unix and frozen?
        # if py34+, else fall back
        if not hasattr(multiprocessing, "get_context"):
            return
        all_methods = multiprocessing.get_all_start_methods()
        logger.info(
            "multiprocessing start_methods={}, using: {}".format(
                ",".join(all_methods), start_method
            )
        )
        ctx = multiprocessing.get_context(start_method)
        self._multiprocessing = ctx

    def ensure_launched(self):
        """Launch backend worker if not running."""
        settings = dict(self._settings or ())
        settings["_log_level"] = self._log_level or logging.DEBUG

        # TODO: this is brittle and should likely be handled directly on the
        # settings object.  Multi-processing blows up when it can't pickle
        # objects.
        if "_early_logger" in settings:
            del settings["_early_logger"]

        self.record_q = self._multiprocessing.Queue()
        self.result_q = self._multiprocessing.Queue()
        if settings.get("start_method") != "thread":
            process_class = self._multiprocessing.Process
        else:
            process_class = BackendThread
            # disable interal process checks since we are one process
            wandb._set_internal_process(disable=True)
        self.wandb_process = process_class(
            target=wandb_internal,
            kwargs=dict(
                settings=settings, record_q=self.record_q, result_q=self.result_q,
            ),
        )
        self.wandb_process.name = "wandb_internal"

        # Support running code without a: __name__ == "__main__"
        save_mod_name = None
        save_mod_path = None
        main_module = sys.modules["__main__"]
        main_mod_spec = getattr(main_module, "__spec__", None)
        main_mod_path = getattr(main_module, "__file__", None)
        main_mod_name = None
        if main_mod_spec:
            main_mod_name = getattr(main_mod_spec, "name", None)
        if main_mod_name is not None:
            save_mod_name = main_mod_name
            main_module.__spec__.name = "wandb.mpmain"
        elif main_mod_path is not None:
            save_mod_path = main_module.__file__
            fname = os.path.join(
                os.path.dirname(wandb.__file__), "mpmain", "__main__.py"
            )
            main_module.__file__ = fname

        logger.info("starting backend process...")
        # Start the process with __name__ == "__main__" workarounds
        self.wandb_process.start()
        self._internal_pid = self.wandb_process.pid
        logger.info(
            "started backend process with pid: {}".format(self.wandb_process.pid)
        )

        # Undo temporary changes from: __name__ == "__main__"
        if save_mod_name:
            main_module.__spec__.name = save_mod_name
        elif save_mod_path:
            main_module.__file__ = save_mod_path

        self.interface = interface.BackendSender(
            process=self.wandb_process, record_q=self.record_q, result_q=self.result_q,
        )

    def server_connect(self):
        """Connect to server."""
        pass

    def server_status(self):
        """Report server status."""
        pass

    def cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        self.interface.join()
        self.wandb_process.join()
        self.record_q.close()
        self.result_q.close()
        # No printing allowed from here until redirect restore!!!
