import unittest.mock

import wandb
import wandb.sdk.verify.verify as wandb_verify
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


def test_print_results(capsys):
    failed_test_or_tests = ["test1", "test2"]
    wandb_verify.print_results(None, warning=True)
    wandb_verify.print_results(failed_test_or_tests[0], warning=False)
    wandb_verify.print_results(failed_test_or_tests, warning=False)
    captured = capsys.readouterr().out
    assert "\u2705" in captured
    assert "\u274c" in captured
    assert captured.count("\u274c") == 2


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
    assert "\u274c" in captured


def test_check_cors_configuration(capsys, monkeypatch):
    with unittest.mock.patch("requests.options") as mock_options:
        options_result = unittest.mock.Mock()
        options_result.headers.get.return_value = None
        mock_options.return_value = options_result

        wandb_verify.check_cors_configuration("", "")

        captured = capsys.readouterr().out
        assert "does not have a valid CORs configuration" in captured


def test_check_large_post_uses_service_api(monkeypatch):
    public_api = unittest.mock.Mock()
    monkeypatch.setattr(wandb_verify.wandb, "Api", lambda: public_api)
    monkeypatch.setattr(wandb_verify.getpass, "getuser", lambda: "test-user")

    assert wandb_verify.check_large_post()

    execute_graphql = public_api._service_api.execute_graphql
    execute_graphql.assert_called_once()
    _, kwargs = execute_graphql.call_args
    assert kwargs["variables"]["entity"] == "test-user"
    assert kwargs["timeout"] == 60


def test_check_large_post_reports_core_413(monkeypatch, capsys):
    error_response = apb.ApiErrorResponse(message="too large", http_status=413)
    public_api = unittest.mock.Mock()
    public_api._service_api.execute_graphql.side_effect = WandbApiFailedError(
        error_response.message,
        error_response,
    )
    monkeypatch.setattr(wandb_verify.wandb, "Api", lambda: public_api)
    monkeypatch.setattr(wandb_verify.getpass, "getuser", lambda: "test-user")

    assert not wandb_verify.check_large_post()

    captured = capsys.readouterr().out
    assert "proxy-body-size" in captured


def test_check_wandb_version(capsys):
    api = unittest.mock.Mock()
    api.viewer_server_info.return_value = (
        None,
        {
            "cliVersionInfo": {
                "min_cli_version": "0.10.0",
                "max_cli_version": "1.0.0",
            }
        },
    )

    with unittest.mock.patch.object(wandb, "__version__", "0.0.1"):
        wandb_verify.check_wandb_version(api)
        captured = capsys.readouterr().out
        assert "wandb version out of date" in captured

    with unittest.mock.patch.object(wandb, "__version__", "100.0.0"):
        wandb_verify.check_wandb_version(api)
        captured = capsys.readouterr().out
        assert "wandb version is not supported" in captured


def test_retry_fn_retries_exceptions():
    i = 0

    def fn():
        nonlocal i
        if i < 1:
            i += 1
            raise Exception("test")
        return "test"

    with unittest.mock.patch("time.sleep", return_value=None):
        result = wandb_verify.retry_fn(fn)
        assert result == "test"


def test_retry_fn_times_out():
    def fn():
        raise Exception("test")

    now = 0

    def time():
        nonlocal now
        return now

    def sleep(seconds):
        nonlocal now
        now += seconds

    with unittest.mock.patch("time.sleep", side_effect=sleep):
        with unittest.mock.patch("time.time", side_effect=time):
            result = wandb_verify.retry_fn(fn)
            assert result is None
