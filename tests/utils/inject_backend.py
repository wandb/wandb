#
"""Backend interface injection / tracing utility.

Example:

import inject_backend as _inject

class InjectBackend(_inject.BackendSenderMock):
    def __init__(self, *args, **kwargs):
        super(InjectBackend, self).__init__(*args, **kwargs)

    def _communicate(self, *args, **kwargs):
        ret = _inject.BackendSenderMock._communicate(self, *args, **kwargs)
        return ret

i = _inject.InjectUtil()
i.install(InjectBackend)
i.uninstall()

"""

import sys

import wandb

try:
    from unittest import mock
except ImportError:
    import mock


_PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if _PY3:
    from wandb.sdk.interface.interface import BackendSender

    BACKEND_SENDER_CLASS = "wandb.sdk.interface.interface.BackendSender"
else:
    from wandb.sdk_py27.interface.interface import BackendSender

    BACKEND_SENDER_CLASS = "wandb.sdk_py27.interface.interface.BackendSender"


class BackendSenderMock(BackendSender):
    def __init__(self, *args, **kwargs):
        super(BackendSenderMock, self).__init__(*args, **kwargs)

    def _communicate(self, *args, **kwargs):
        ret = BackendSender._communicate(self, *args, **kwargs)
        return ret


class InjectUtil:
    def __init__(self):
        self._patcher = None

    def install(self, mock_class):
        assert issubclass(
            mock_class, BackendSenderMock
        ), "Must install a class derived from BackendSenderMock"
        self._patcher = mock.patch(BACKEND_SENDER_CLASS, mock_class)
        MockClass = self._patcher.start()

    def uninstall(self):
        if self._patcher:
            self._patcher.stop()
            self._patcher = None
