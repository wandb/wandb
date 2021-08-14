from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.errors import InputTimeoutError
from wandb.util import prompt_choices, _prompt_choice_with_timeout
import io
import pytest


@pytest.fixture
def stdin_tests(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("1"))
    choice = stdin_timeout("", None, "")
    assert choice == "1"

    choices = ["1", "2"]
    choice = prompt_choices(choices)
    assert choice == "1"

    choice = _prompt_choice_with_timeout()
    assert choice == 0

""""
@pytest.fixture
def input_timeout_test(pytestconfig):
    capmanager = pytestconfig.pluginmanager.getplugin('capturemanager')
    capmanager.suspend_global_capture(_in=True)

    timeout_log = "input timeout!"
    try:
        stdin_timeout("waiting for input", 1, timeout_log)
    except InputTimeoutError as e:
        assert e.message == timeout_log
    capmanager.resume_global_capture()
"""
