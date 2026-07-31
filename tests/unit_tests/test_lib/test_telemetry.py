"""telemetry lib tests."""

import threading
from collections import defaultdict

from wandb import env
from wandb.analytics.opentelemetry import opentelemetry_proxy
from wandb.analytics.opentelemetry.opentelemetry_proxy import (
    OtelProvider,
    TelemetryRecorder,
    get_otel,
)
from wandb.sdk.lib import telemetry


def test_disabled_otel_provider_records_as_noop(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: False)
    provider = OtelProvider(auth_provider=None)
    recorder = TelemetryRecorder(root=provider)

    recorder.increment_counter_and_log_event("test")
    recorder.exception("test", RuntimeError("test"))


def test_get_otel_caches_providers_per_host(monkeypatch):
    class FakeOtelProvider:
        def __init__(self, **kwargs):
            self._pid = kwargs["pid"]
            self.endpoint = kwargs["endpoint"]
            self.metrics = []

        def increment_counter(self, name, low_cardinality_attributes):
            self.metrics.append(name)

        def log(self, message, attributes, severity):
            pass

    monkeypatch.setattr(opentelemetry_proxy, "OtelProvider", FakeOtelProvider)
    monkeypatch.setattr(opentelemetry_proxy, "_provider_cache", {})
    monkeypatch.setattr(
        opentelemetry_proxy,
        "_provider_initialization_locks",
        defaultdict(threading.Lock),
    )

    first_host_provider = get_otel(
        base_url="https://first.example.com",
        auth_provider=lambda: None,
    )
    second_host_provider = get_otel(
        base_url="https://second.example.com",
        auth_provider=lambda: None,
    )
    # Third provider should be the same object as the first provider.
    third_host_provider = get_otel(base_url="https://first.example.com/")

    assert first_host_provider is not None
    assert second_host_provider is not None
    assert third_host_provider is first_host_provider
    assert first_host_provider is not second_host_provider
    assert isinstance(first_host_provider, FakeOtelProvider)
    assert isinstance(second_host_provider, FakeOtelProvider)
    assert isinstance(third_host_provider, FakeOtelProvider)

    TelemetryRecorder(root=first_host_provider).increment_counter_and_log_event(
        "first_host_metric"
    )
    TelemetryRecorder(root=second_host_provider).increment_counter_and_log_event(
        "second_host_metric"
    )
    TelemetryRecorder(root=third_host_provider).increment_counter_and_log_event(
        "third_host_metric"
    )

    assert first_host_provider.metrics == ["first_host_metric", "third_host_metric"]
    assert third_host_provider.metrics == ["first_host_metric", "third_host_metric"]
    assert second_host_provider.metrics == ["second_host_metric"]

    assert first_host_provider.metrics == third_host_provider.metrics
    assert "second_host_metric" not in first_host_provider.metrics
    assert "first_host_metric" not in second_host_provider.metrics


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
