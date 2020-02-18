"""
setup.
"""

import threading


class _WandbLibrary__WandbLibrary(object):
    """Inner class of _WandbLibrary."""
    def __init__(self):
        self.check()

    def check(self):
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                print("bad thread")
        elif threading.current_thread().name != 'MainThread':
            print("bad thread2", threading.current_thread().name)


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
