"""telemetry lib tests."""

from unittest.mock import MagicMock

import pytest
from wandb import env
from wandb.analytics.opentelemetry import opentelemetry_proxy
from wandb.analytics.opentelemetry.opentelemetry_proxy import (
    LowCardinalityAttributes,
    TelemetryRecorder,
    get_telemetry_recorder,
)
from wandb.sdk import wandb_setup
from wandb.sdk.lib import telemetry
from wandb.sdk.wandb_settings import Settings


def _pretend_service_connected(monkeypatch):
    """Make the telemetry publish path see an existing service connection."""
    fake_setup = MagicMock(service_connected=True)
    monkeypatch.setattr(wandb_setup, "singleton_if_created", lambda: fake_setup)


def test_telemetry_parse():
    pf = telemetry._parse_label_lines

    assert pf(["nothin", "dontcare", "@wandbcode{hello}"]) == dict(code="hello")
    assert pf(["", "  @wandbcode{hi-there, junk=2}"]) == dict(code="hi_there", junk="2")
    assert pf(["@wandbcode{hello, junk=2}"]) == dict(code="hello", junk="2")
    assert pf(["@wandbcode{}", "junk", "@wandbcode{ignore}"]) == dict()
    assert pf(['@wandbcode{h, j="iquote", p=hhh}']) == dict(
        code="h", j="iquote", p="hhh"
    )
    assert pf(['@wandbcode{h, j="i,e", p=hhh}']) == dict(code="h", p="hhh")
    assert pf(["@wandbcode{j=i-p,"]) == dict(j="i_p")


def test_disabled_telemetry_does_not_publish(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: False)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter_and_log_event("test")
    recorder.exception(Exception("test"))

    service_api.api_publish.assert_not_called()


def test_telemetry_without_service_api_does_not_publish():
    recorder = TelemetryRecorder()

    assert recorder._can_publish() is False

    # even if we cannot publish, calling the methods should still be safe
    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")
    recorder.increment_counter_and_log_event("test event")
    recorder.exception(Exception("test exception"))


def test_errors_do_not_propagate_from_telemetry(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    _pretend_service_connected(monkeypatch)
    service_api = MagicMock()
    service_api.api_publish.side_effect = OSError("service connection closed")
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter(
        "test_counter",
        LowCardinalityAttributes(),
    )
    recorder.log("test log")

    assert service_api.api_publish.call_count == 2


def test_reraise_raises_original_on_telemetry_fail(monkeypatch):
    """`reraise` must always re-raise the original exception, even if recording
    telemetry itself fails."""
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    _pretend_service_connected(monkeypatch)
    monkeypatch.setattr(
        opentelemetry_proxy,
        "OpenTelemetryLogRequest",
        MagicMock(side_effect=ValueError()),
    )
    recorder = TelemetryRecorder(service_api=MagicMock())

    original = RuntimeError("original error")
    with pytest.raises(RuntimeError, match="original error") as exc_info:
        recorder.reraise(original)

    assert exc_info.value is original


def test_telemetry_does_not_publish_without_service_connection(monkeypatch):
    monkeypatch.setattr(opentelemetry_proxy, "_recorder_pool", {})
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")
    recorder.increment_counter_and_log_event("test event")
    recorder.exception(Exception("test exception"))

    service_api.api_publish.assert_not_called()


def test_telemetry_publishes_with_service_connection(monkeypatch):
    monkeypatch.setattr(opentelemetry_proxy, "_recorder_pool", {})
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    _pretend_service_connected(monkeypatch)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")

    assert service_api.api_publish.call_count == 2


def test_get_telemetry_recorder_shares_per_deployment_and_credentials(monkeypatch):
    monkeypatch.setattr(opentelemetry_proxy, "_recorder_pool", {})
    user_1 = get_telemetry_recorder(
        Settings(base_url="https://host-a.test", api_key="user-1-key")
    )
    user_1_again = get_telemetry_recorder(
        Settings(base_url="https://host-a.test", api_key="user-1-key")
    )
    user_2 = get_telemetry_recorder(
        Settings(base_url="https://host-a.test", api_key="user-2-key")
    )
    user_3 = get_telemetry_recorder(
        Settings(base_url="https://host-a.test", identity_token_file="user-3-token")
    )
    other_host = get_telemetry_recorder(
        Settings(base_url="https://host-b.test", api_key="user-1-key")
    )

    assert user_1 is user_1_again
    assert user_1 is not user_2
    assert user_1 is not user_3
    assert user_1 is not other_host
