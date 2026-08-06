"""telemetry lib tests."""

from wandb import env
from wandb.analytics.opentelemetry.opentelemetry_proxy import (
    OtelProvider,
    TelemetryRecorder,
)
from wandb.sdk.lib import telemetry


def test_disabled_otel_provider_records_as_noop(monkeypatch):
    monkeypatch.setattr(env, "error_reporting_enabled", lambda: False)
    provider = OtelProvider(api_key="")
    recorder = TelemetryRecorder(root=provider)

    recorder.increment_counter_and_log_event("test")
    recorder.exception("test", RuntimeError("test"))


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
