"""
setup.
"""

import threading
import multiprocessing
import sys


class _WandbLibrary__WandbLibrary(object):
    """Inner class of _WandbLibrary."""
    def __init__(self):
        #print("setup")
        self._multiprocessing = None
        self.check()
        self.setup()

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

    def __init__(self):
        if _WandbLibrary._instance is not None:
            return
        _WandbLibrary._instance = __WandbLibrary()

    def __getattr__(self, name):
        return getattr(self._instance, name)


def setup(settings=None):
    """Setup library context."""
    wl = _WandbLibrary()
    return wl
