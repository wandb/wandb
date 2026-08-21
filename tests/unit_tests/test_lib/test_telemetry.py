"""telemetry lib tests."""

import threading
from unittest.mock import MagicMock

import pytest
from wandb import env
from wandb.analytics.opentelemetry import opentelemetry_proxy
from wandb.analytics.opentelemetry.opentelemetry_proxy import (
    LowCardinalityAttributes,
    OpenTelemetryProxy,
    TelemetryRecorder,
    disable,
)
from wandb.sdk.lib import telemetry
from wandb.sdk.wandb_settings import Settings


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


def test_no_error_reporting_telemetry_does_not_publish(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: False)
    open_telemetry_proxy = MagicMock()
    recorder = TelemetryRecorder(open_telemetry_proxy=open_telemetry_proxy)

    recorder.increment_counter_and_log_event("test")
    recorder.exception(Exception("test"))

    open_telemetry_proxy.increment_counter.assert_not_called()
    open_telemetry_proxy.log.assert_not_called()


def test_disabled_telemetry_does_not_publish(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    monkeypatch.setattr(opentelemetry_proxy, "_disabled", threading.Event())

    disable()

    open_telemetry_proxy = OpenTelemetryProxy.from_settings(settings=Settings())
    assert open_telemetry_proxy is None

    recorder = TelemetryRecorder(open_telemetry_proxy=open_telemetry_proxy)

    recorder.increment_counter_and_log_event("test")
    recorder.exception(Exception("test"))


def test_telemetry_without_proxy_does_not_publish():
    open_telemetry_proxy = MagicMock()
    recorder = TelemetryRecorder(open_telemetry_proxy=None)

    recorder.increment_counter("test_counter", LowCardinalityAttributes())
    recorder.log("test log")
    recorder.increment_counter_and_log_event("test event")
    recorder.exception(Exception("test exception"))

    open_telemetry_proxy.increment_counter.assert_not_called()
    open_telemetry_proxy.log.assert_not_called()


def test_errors_do_not_propagate_from_telemetry(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    # _pretend_service_connected(monkeypatch)
    open_telemetry_proxy = MagicMock()
    open_telemetry_proxy.increment_counter.side_effect = RuntimeError()
    recorder = TelemetryRecorder(open_telemetry_proxy=open_telemetry_proxy)

    recorder.increment_counter(
        "test_counter",
        LowCardinalityAttributes(),
    )
    recorder.log("test log")

    assert open_telemetry_proxy.increment_counter.call_count == 1
    assert open_telemetry_proxy.log.call_count == 1


def test_reraise_raises_original_on_telemetry_fail(monkeypatch):
    """`reraise` must always re-raise the original exception, even if recording
    telemetry itself fails."""
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: True)
    open_telemetry_proxy = MagicMock()
    open_telemetry_proxy.log.side_effect = ValueError()
    recorder = TelemetryRecorder(open_telemetry_proxy=open_telemetry_proxy)

    original = RuntimeError("original error")
    with pytest.raises(RuntimeError, match="original error") as exc_info:
        recorder.reraise(original)

    assert exc_info.value is original
