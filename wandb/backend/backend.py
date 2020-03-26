# -*- coding: utf-8 -*-
"""Backend - Send to internal process

Manage backend.

"""

import threading
import json
from six.moves import queue
import sys
import os
import logging
import six
import multiprocessing
from datetime import date, datetime
import time
from wandb.interface import interface

import wandb

from wandb.internal.internal import wandb_internal
from wandb.interface import constants

import platform

logger = logging.getLogger("wandb")


class Backend(object):

    def __init__(self, mode=None):
        self.wandb_process = None
        self.fd_pipe_parent = None
        self.process_queue = None
        # self.fd_request_queue = None
        # self.fd_response_queue = None
        self.req_queue = None
        self.resp_queue = None
        self.cancel_queue = None
        self.notify_queue = None  # notify activity on ...

        self._done = False
        self._wl = wandb.setup()
        self.interface = None

    def _hack_set_run(self, run):
        self.interface._hack_set_run(run)

    def ensure_launched(self, settings=None, log_fname=None, log_level=None, data_fname=None, stdout_fd=None, stderr_fd=None, use_redirect=None):
        """Launch backend worker if not running."""
        log_fname = log_fname or ""
        log_level = log_level or logging.DEBUG
        settings = settings or {}
        settings = dict(settings)

        #os.set_inheritable(stdout_fd, True)
        #os.set_inheritable(stderr_fd, True)
        #stdout_read_file = os.fdopen(stdout_fd, 'rb')
        #stderr_read_file = os.fdopen(stderr_fd, 'rb')

        fd_pipe_child, fd_pipe_parent = self._wl._multiprocessing.Pipe()

        process_queue = self._wl._multiprocessing.Queue()
        # async_queue = self._wl._multiprocessing.Queue()
        # fd_request_queue = self._wl._multiprocessing.Queue()
        # fd_response_queue = self._wl._multiprocessing.Queue()
        # TODO: should this be one item just to make sure it stays fully synchronous?
        req_queue = self._wl._multiprocessing.Queue()
        resp_queue = self._wl._multiprocessing.Queue()
        cancel_queue = self._wl._multiprocessing.Queue()
        notify_queue = self._wl._multiprocessing.Queue()

        wandb_process = self._wl._multiprocessing.Process(target=wandb_internal,
                args=(
                    settings,
                    notify_queue,
                    process_queue,
                    req_queue,
                    resp_queue,
                    cancel_queue,
                    fd_pipe_child,
                    log_fname,
                    log_level,
                    data_fname,
                    use_redirect,
                    ))
        wandb_process.name = "wandb_internal"

        # Support running code without a: __name__ == "__main__"
        save_mod_name = None
        save_mod_path = None
        main_module = sys.modules['__main__']
        main_mod_spec = getattr(main_module, "__spec__", None)
        main_mod_path = getattr(main_module, '__file__', None)
        main_mod_name = None
        if main_mod_spec:
            main_mod_name = getattr(main_mod_spec, "name", None)
        if main_mod_name is not None:
            save_mod_name = main_mod_name
            main_module.__spec__.name = "wandb.internal.mpmain"
        elif main_mod_path is not None:
            save_mod_path = main_module.__file__
            fname = os.path.join(os.path.dirname(wandb.__file__), "internal", "mpmain", "__main__.py")
            main_module.__file__ = fname

        # Start the process with __name__ == "__main__" workarounds
        wandb_process.start()

        if use_redirect:
            pass
        else:
            if platform.system() == "Windows":
                # https://bugs.python.org/issue38188
                #import msvcrt
                #print("DEBUG1: {}".format(stdout_fd))
                #stdout_fd = msvcrt.get_osfhandle(stdout_fd)
                #print("DEBUG2: {}".format(stdout_fd))
                # stderr_fd = msvcrt.get_osfhandle(stderr_fd)
                #multiprocessing.reduction.send_handle(fd_pipe_parent, stdout_fd,  wandb_process.pid)
                # multiprocessing.reduction.send_handle(fd_pipe_parent, stderr_fd,  wandb_process.pid)

                # should we do this?
                #os.close(stdout_fd)
                #os.close(stderr_fd)
                pass
            else:
                multiprocessing.reduction.send_handle(fd_pipe_parent, stdout_fd,  wandb_process.pid)
                multiprocessing.reduction.send_handle(fd_pipe_parent, stderr_fd,  wandb_process.pid)

                # should we do this?
                os.close(stdout_fd)
                os.close(stderr_fd)

        # Undo temporary changes from: __name__ == "__main__"
        if save_mod_name:
            main_module.__spec__.name = save_mod_name
        elif save_mod_path:
            main_module.__file__ = save_mod_path

        self.fd_pipe_parent = fd_pipe_parent

        self.wandb_process = wandb_process

        self.process_queue = process_queue
        # self.async_queue = async_queue
        # self.fd_request_queue = fd_request_queue
        # self.fd_response_queue = fd_response_queue
        self.req_queue = req_queue
        self.resp_queue = resp_queue
        self.cancel_queue = cancel_queue
        self.notify_queue = notify_queue

        self.interface = interface.BackendSender(
                notify_queue=notify_queue,
                process_queue=process_queue,
                request_queue=req_queue,
                response_queue=resp_queue,
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

        self.notify_queue.put(constants.NOTIFY_SHUTDOWN)
        # TODO: make sure this is last in the queue?  lock?
        self.notify_queue.close()
        self.wandb_process.join()
        # No printing allowed from here until redirect restore!!!
