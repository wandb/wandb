"""telemetry lib tests."""

from unittest.mock import MagicMock

from wandb import env
from wandb.analytics.opentelemetry.opentelemetry_proxy import (
    LowCardinalityAttributes,
    TelemetryRecorder,
)
from wandb.sdk import wandb_setup


def _pretend_service_connected(monkeypatch):
    """Make the telemetry publish path see an existing service connection."""
    fake_setup = MagicMock(service_connected=True)
    monkeypatch.setattr(wandb_setup, "singleton_if_created", lambda: fake_setup)


def test_disabled_telemetry_does_not_publish(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: False)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter_and_log_event("test")
    recorder.exception("test", RuntimeError("test"))

    service_api.api_publish.assert_not_called()


def test_telemetry_without_service_api_does_not_publish(mocker):
    publish = mocker.patch.object(TelemetryRecorder, "_publish")
    recorder = TelemetryRecorder()

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")
    recorder.increment_counter_and_log_event("test event")
    recorder.exception("test exception", RuntimeError("test"))

    publish.assert_not_called()


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


def test_telemetry_does_not_publish_without_service_connection(monkeypatch):
    """Telemetry must never publish (and so never start wandb-core) unless a
    service connection already exists."""
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")
    recorder.increment_counter_and_log_event("test event")
    recorder.exception("test exception", RuntimeError("test"))

    service_api.api_publish.assert_not_called()


def test_telemetry_publishes_with_service_connection(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    _pretend_service_connected(monkeypatch)
    service_api = MagicMock()
    recorder = TelemetryRecorder(service_api=service_api)

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")

    assert service_api.api_publish.call_count == 2
