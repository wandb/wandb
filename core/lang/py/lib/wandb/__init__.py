"""wandb library."""

from wandb.proto import wandb_internal_pb2

__version__ = "0.0.1"

class Session:
    def __init__(self):
        import ctypes
        import os
        import pathlib
        lib_path = pathlib.Path(__file__).parent / "lib" / "libwandb_core.so"
        self._lib = ctypes.cdll.LoadLibrary(lib_path)
        self._lib.pbSessionSetup()

class Run:
    def __init__(self):
        pass

    def log(self):
        pass

    def _start(self):
        global _session
        if _session:
            setup()
        self._session = _session
        self._run_nexus_id = self._session._lib.pbRunStart()

    def finish(self):
        self._session._lib.pbRunFinish(self._run_nexus_id)


# global session
_session = None


def setup():
    global _session
    if _session:
        return
    _session = Session()


def init(*args, **kwargs):
    setup()
    r = Run()
    r._start()
    return r


def teardown():
    global _session
    _session = None
