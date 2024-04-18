"""wandb library."""

from wandb.proto import wandb_internal_pb2 as pb2

class _Library:
    def __init__(self):
        self._obj = None

    @property
    def _lib(self):
        if not self._obj:
            import ctypes
            import os
            import pathlib
            lib_path = pathlib.Path(__file__).parent / "lib" / "libwandb_core.so"
            self._obj = ctypes.cdll.LoadLibrary(lib_path)
        return self._obj

    def new_session(self) -> "Session":
        return Session(_library=self)

    def teardown(self):
        pass


# global library object
_library = _Library()


class Session:
    def __init__(self, _library):
        self._library = _library
        self._loaded = False
        self._last_run = None

    @property
    def _lib(self):
        return self._library._lib

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._lib.pbSessionSetup()
        self._loaded = True

    def configure_auth(self):
        self._ensure_loaded()
        pass

    def login(self):
        self._ensure_loaded()
        pass

    def new_run(self) -> "Run":
        self._ensure_loaded()
        run = Run(_session=self)
        run._start()
        self._last_run = run
        return run

    def teardown(self):
        pass


def new_session() -> Session:
    return _library.new_session()


class Run:
    def __init__(self, _session):
        self._session = _session
        self._run_nexus_id = None

    @property
    def _lib(self):
        return self._session._lib

    def log(self, data):
        data_msg = pb2.DataRecord()
        for k, v in data.items():
            if type(v) == int:
                data_msg.item[k].value_int = v
            elif type(v) == float:
                data_msg.item[k].value_double = v
            elif type(v) == str:
                data_msg.item[k].value_string = v
        data_bytes = data_msg.SerializeToString()
        # input_buffer = create_string_buffer(data_bytes)
        self._lib.pbRunLog(self._run_nexus_id, data_bytes, len(data_bytes))

    def _start(self):
        self._run_nexus_id = self._lib.pbRunStart()

    def finish(self):
        self._lib.pbRunFinish(self._run_nexus_id)


# global default session object
default_session = new_session()


# ---
# wandb 0.x Compatibility
# ---

def setup():
    default_session._ensure_loaded()


def init(*args, **kwargs):
    return default_session.new_run()

def log(*args, **kwargs):
    default_session._last_run.log(data)

def teardown():
    global _session
    _session = None
