import sys

# TODO: consolidate dynamic imports
PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.lib import _inject
else:
    from wandb.sdk_py27.lib import _inject


class InjectUtil:
    def __init__(self):
        self._inject_communicate = _inject.inject_communicate
        self._inject = _inject

    def install(self, fn):
        _inject.inject_communicate = fn

    def cleanup(self):
        self.install(self._inject_communicate)
