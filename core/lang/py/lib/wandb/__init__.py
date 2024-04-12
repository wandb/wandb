"""wandb library."""

from wandb.proto import wandb_internal_pb2

__version__ = "0.0.1"

class Session:
    def __init__(self):
        pass

class Run:
    def __init__(self):
        pass

    def log(self):
        pass

    def _start(self):
        print("Starting run...")

    def finish(self):
        print("Finishing run...")


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
