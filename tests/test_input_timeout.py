from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.errors import InputTimeoutError
import io
import pytest


@pytest.fixture
def input_timeout(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("1"))
    choice = stdin_timeout("", None, "")
    assert choice == "1"


"""
@pytest.fixture
def setup(pytestconfig):
    capmanager = pytestconfig.pluginmanager.getplugin('capturemanager')
    capmanager.suspend_global_capture(_in=True)

    timeout_log = "input timeout!"
    try:
        stdin_timeout("waiting for input", 1, timeout_log)
    except InputTimeoutError as e:
        assert e.message == timeout_log
    capmanager.resume_global_capture()
"""
