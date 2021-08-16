from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.errors import InputTimeoutError


def test_timeout(pytestconfig):
    capmanager = pytestconfig.pluginmanager.getplugin("capturemanager")
    capmanager.suspend_global_capture(in_=True)

    timeout_log = "input timeout!"
    try:
        stdin_timeout("waiting for input", 1, timeout_log)
    except InputTimeoutError as e:
        assert e.message == timeout_log
    capmanager.resume_global_capture()
