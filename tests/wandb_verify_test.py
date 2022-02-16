import time
from unittest import mock

import wandb
from wandb.apis import InternalApi
import wandb.sdk.verify.verify as wandb_verify


def test_print_results(capsys):
    failed_test_or_tests = ["test1", "test2"]
    wandb_verify.print_results(None, warning=True)
    wandb_verify.print_results(failed_test_or_tests[0], warning=False)
    wandb_verify.print_results(failed_test_or_tests, warning=False)
    captured = capsys.readouterr().out
    assert u"\u2705" in captured
    assert u"\u274C" in captured
    assert captured.count(u"\u274C") == 2


def test_check_host():
    assert not wandb_verify.check_host("https://api.wandb.ai")
    assert wandb_verify.check_host("http://localhost:8000")


def test_check_logged_in(live_mock_server, test_settings):
    internal_api = mock.MagicMock(spec=InternalApi)
    internal_api.api_key = None
    assert not wandb_verify.check_logged_in(internal_api, "localhost:8000")

    run = wandb.init(settings=test_settings)
    assert wandb_verify.check_logged_in(InternalApi(), run.settings.base_url)


def test_check_secure_requests(capsys):
    wandb_verify.check_secure_requests(
        "https://wandb.rules",
        "Checking requests to base url",
        "Connections are not made over https. SSL required for secure communications.",
    )
    wandb_verify.check_secure_requests(
        "http://wandb.rules",
        "Checking requests to base url",
        "Connections are not made over https. SSL required for secure communications.",
    )
    captured = capsys.readouterr().out
    assert u"\u2705" in captured
    assert u"\u274C" in captured


def test_check_cors_configuration(live_mock_server, test_settings, capsys):
    wandb_verify.check_cors_configuration(
        test_settings.base_url, "localhost",
    )
    captured = capsys.readouterr().out
    assert u"\u274C" in captured


def test_check_wandb_version(live_mock_server, capsys):
    wandb_verify.check_wandb_version(InternalApi())
    captured = capsys.readouterr().out
    assert u"\u274C" not in captured


def test_retry_fn():
    i = 0

    def fn():
        nonlocal i
        if i < 1:
            i += 1
            raise Exception("test")
        return "test"

    result = wandb_verify.retry_fn(fn)
    assert result == "test"

    j = 0

    def fn2():
        nonlocal j
        if j == 0:
            time.sleep(10)
        if j < 4:  # retry 4 times
            j += 1
            raise Exception("test")
        return "test"

    result = wandb_verify.retry_fn(fn2)
    assert result is None
