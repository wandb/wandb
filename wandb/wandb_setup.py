"""
setup.
"""

import threading
import multiprocessing
import sys
import os
import datetime
import errno
import logging


logger = logging.getLogger("wandb")

class _WandbLibrary__WandbLibrary(object):
    """Inner class of _WandbLibrary."""
    def __init__(self, settings=None):
        #print("setup")
        self._multiprocessing = None
        self._settings = settings
        self._log_user_filename = None
        self._log_internal_filename = None
        self.log_setup()
        self.check()
        self.setup()

    def enable_logging(self, log_fname, run_id=None):
        """Enable logging to the global debug log.  This adds a run_id to the log,
        in case of muliple processes on the same machine.

        Currently no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(log_fname)
        handler.setLevel(logging.INFO)

        class WBFilter(logging.Filter):
            def filter(self, record):
                record.run_id = run_id
                return True

        if run_id:
            formatter = logging.Formatter(
                '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s')
        else:
            formatter = logging.Formatter(
                '%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d [%(filename)s:%(funcName)s():%(lineno)s] %(message)s')

        handler.setFormatter(formatter)
        if run_id:
            handler.addFilter(WBFilter())
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    def log_setup(self):
        # log dir - where python logs go
        log_dir = "wandb"
        # log spec
        log_user_spec = "wandb-debug-{timespec}-{pid}-user.txt"
        log_internal_spec = "wandb-debug-{timespec}-{pid}-internal.txt"
        # TODO(jhr): should we use utc?
        when = datetime.datetime.now()
        pid = os.getpid()
        datestr = datetime.datetime.strftime(when, "%Y%m%d_%H%M%S")
        d = dict(pid=pid, timespec=datestr)
        log_user = os.path.join(log_dir, log_user_spec.format(**d))
        log_internal = os.path.join(log_dir, log_internal_spec.format(**d))
        try:
            os.makedirs(log_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        if not os.path.isdir(log_dir):
            raise Exception("not dir")
        if not os.access(log_dir, os.W_OK):
            raise Exception("cant write: {}".format(log_dir))
        #print("loguser", log_user)
        #print("loginternal", log_internal)
        self.enable_logging(log_user)

        logger.info("Logging to {}".format(log_user))
        self._log_user_filename = log_user
        self._log_internal_filename = log_internal

    def check(self):
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                print("bad thread")
        elif threading.current_thread().name != 'MainThread':
            print("bad thread2", threading.current_thread().name)
        if getattr(sys, 'frozen', False):
            print("frozen, could be trouble")
        #print("t2", multiprocessing.get_start_method(allow_none=True))
        #print("t3", multiprocessing.get_start_method())

    def setup(self):
        #TODO: use fork context if unix and frozen?
        # if py34+, else fall back
        if hasattr(multiprocessing, "get_context"):
            all_methods = multiprocessing.get_all_start_methods()
            print("DEBUG: start_methods=", ','.join(all_methods))
            ctx = multiprocessing.get_context('spawn')
        else:
            print("warning, likely using fork on unix")
            ctx = multiprocessing
        self._multiprocessing = ctx
        #print("t3b", self._multiprocessing.get_start_method())


class _WandbLibrary(object):
    """Wandb singleton class."""
    _instance = None

    def __init__(self, settings=None):
        # TODO(jhr): what do we do if settings changed?
        if _WandbLibrary._instance is not None:
            return
        _WandbLibrary._instance = __WandbLibrary(settings=settings)

    def __getattr__(self, name):
        return getattr(self._instance, name)


def setup(settings=None):
    """Setup library context."""
    wl = _WandbLibrary(settings=settings)
    return wl
