"""
init tests.
"""

import pytest
import wandb

from .utils import inject_backend


def test_inject_init_none(live_mock_server, test_settings, inject_util):
    """Use injection framework, but don't inject anything."""

    class InjectBackend(inject_backend.BackendSenderMock):
        def __init__(self, *args, **kwargs):
            super(InjectBackend, self).__init__(*args, **kwargs)

        def _communicate(self, *args, **kwargs):
            ret = inject_backend.BackendSenderMock._communicate(self, *args, **kwargs)
            return ret

    inject_util.install(InjectBackend)
    run = wandb.init()
    run.finish()


def test_inject_init_health(live_mock_server, test_settings, inject_util):
    """Drop health message to simulate problem starting int process."""

    class InjectBackend(inject_backend.BackendSenderMock):
        def _communicate(self, *args, **kwargs):
            inject_util.uninstall()
            return

    inject_util.install(InjectBackend)
    with pytest.raises(wandb.errors.InitStartError):
        run = wandb.init()


def test_inject_init_interrupt(live_mock_server, test_settings, inject_util):
    """On health check meessage, send control-c."""

    class InjectBackend(inject_backend.BackendSenderMock):
        def _communicate(self, *args, **kwargs):
            inject_util.uninstall()
            raise KeyboardInterrupt()

    inject_util.install(InjectBackend)
    with pytest.raises(KeyboardInterrupt):
        run = wandb.init()


def test_inject_init_generic(live_mock_server, test_settings, inject_util):
    """On health check meessage, send generic Exception."""

    class InjectBackend(inject_backend.BackendSenderMock):
        def _communicate(self, *args, **kwargs):
            inject_util.uninstall()
            raise Exception("This is generic")

    inject_util.install(InjectBackend)
    with pytest.raises(wandb.errors.InitGenericError):
        run = wandb.init()


def test_inject_init_abort_fail(live_mock_server, test_settings, inject_util):
    """On health check meessage, send generic Exception. abort fail too."""

    class InjectBackend(inject_backend.BackendSenderMock):
        def _communicate(self, *args, **kwargs):
            raise Exception("This is generic")

    inject_util.install(InjectBackend)
    with pytest.raises(wandb.errors.InitGenericError):
        run = wandb.init()
