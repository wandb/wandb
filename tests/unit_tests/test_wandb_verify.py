import time
import unittest.mock

import wandb
import wandb.sdk.verify.verify as wandb_verify
from wandb.apis import InternalApi


def test_check_logged_in(wandb_init):
    internal_api = unittest.mock.MagicMock(spec=InternalApi)
    internal_api.api_key = None
    assert not wandb_verify.check_logged_in(internal_api, "localhost:8000")

    run = wandb_init()
    assert wandb_verify.check_logged_in(InternalApi(), run.settings.base_url)
    run.finish()


def test_print_results(capsys):
    failed_test_or_tests = ["test1", "test2"]
    wandb_verify.print_results(None, warning=True)
    wandb_verify.print_results(failed_test_or_tests[0], warning=False)
    wandb_verify.print_results(failed_test_or_tests, warning=False)
    captured = capsys.readouterr().out
    assert "\u2705" in captured
    assert "\u274C" in captured
    assert captured.count("\u274C") == 2


def test_check_host():
    assert not wandb_verify.check_host("https://api.wandb.ai")
    assert wandb_verify.check_host("http://localhost:8000")


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
    assert "\u2705" in captured
    assert "\u274C" in captured


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


def test_check_cors_configuration(test_settings, capsys):
    wandb_verify.check_cors_configuration(
        test_settings().base_url,
        "localhost",
    )
    captured = capsys.readouterr().out
    assert "\u274C" in captured


def test_check_wandb_version(capsys):
    api = InternalApi()

    not_enough, too_much = "0.0.1", "100.0.0"
    for version in [not_enough, too_much]:
        with unittest.mock.patch.object(wandb, "__version__", version):
            wandb_verify.check_wandb_version(api)
            captured = capsys.readouterr().out
            assert "\u274C" in captured
