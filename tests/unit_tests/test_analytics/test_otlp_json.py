"""Tests for the custom OTLP/JSON exporters and encoder.

These verify that wandb can emit OpenTelemetry metrics and logs over OTLP/JSON
without the protobuf-bound ``opentelemetry-proto`` package.
"""

from __future__ import annotations

import http.server
import json
import threading
import time

import pytest
from wandb.analytics import _otlp_json


# --------------------------------------------------------------------------- #
# Encoder unit tests
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, expected",
    [
        ("hi", {"stringValue": "hi"}),
        (True, {"boolValue": True}),
        (False, {"boolValue": False}),
        (7, {"intValue": "7"}),  # 64-bit ints are JSON strings
        (1.5, {"doubleValue": 1.5}),
        (None, {}),
        (
            [1, "a"],
            {"arrayValue": {"values": [{"intValue": "1"}, {"stringValue": "a"}]}},
        ),
        (
            {"k": 2},
            {"kvlistValue": {"values": [{"key": "k", "value": {"intValue": "2"}}]}},
        ),
    ],
)
def test_any_value_encoding(value, expected):
    assert _otlp_json._any_value(value) == expected


def test_attributes_encoding():
    assert _otlp_json._attributes({"a": "x", "n": 3}) == [
        {"key": "a", "value": {"stringValue": "x"}},
        {"key": "n", "value": {"intValue": "3"}},
    ]


def test_encode_metrics_counter_roundtrip():
    """A delta counter is encoded as a monotonic Sum with string ints."""
    from opentelemetry.sdk.metrics import Counter, MeterProvider
    from opentelemetry.sdk.metrics.export import (
        AggregationTemporality,
        InMemoryMetricReader,
    )

    reader = InMemoryMetricReader(
        preferred_temporality={Counter: AggregationTemporality.DELTA},
    )
    provider = MeterProvider(metric_readers=[reader])
    counter = provider.get_meter("test").create_counter("my_counter")
    counter.add(3, attributes={"color": "blue"})

    metrics_data = reader.get_metrics_data()
    payload = _otlp_json.encode_metrics(metrics_data)

    metric = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
    assert metric["name"] == "my_counter"
    sum_data = metric["sum"]
    assert sum_data["isMonotonic"] is True
    assert sum_data["aggregationTemporality"] == AggregationTemporality.DELTA.value
    dp = sum_data["dataPoints"][0]
    assert dp["asInt"] == "3"
    assert isinstance(dp["timeUnixNano"], str)
    assert dp["attributes"] == [{"key": "color", "value": {"stringValue": "blue"}}]


def test_encode_logs_roundtrip():
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import LogExporter, SimpleLogRecordProcessor

    captured: list = []

    class _Probe(LogExporter):
        def export(self, batch):
            captured.extend(batch)

        def shutdown(self):
            pass

    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(_Probe()))
    provider.get_logger("test").emit(
        body="boom",
        severity_number=SeverityNumber.ERROR,
        attributes={"run_id": "abc"},
    )
    provider.force_flush()

    payload = _otlp_json.encode_logs(captured)
    record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["body"] == {"stringValue": "boom"}
    assert record["severityNumber"] == SeverityNumber.ERROR.value
    assert record["attributes"] == [{"key": "run_id", "value": {"stringValue": "abc"}}]


# --------------------------------------------------------------------------- #
# End-to-end: the proxy emits OTLP/JSON to a local collector (no protobuf).
# --------------------------------------------------------------------------- #
class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.captured.append(  # type: ignore[attr-defined]
            (self.path, json.loads(body), self.headers.get("Content-Type"))
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        pass


class _CaptureServer:
    def __init__(self) -> None:
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self._httpd.captured = []  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._thread.join(timeout=5)
        self._httpd.server_close()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def captured(self) -> list:
        return self._httpd.captured  # type: ignore[attr-defined]


def test_proxy_emits_otlp_json_without_protobuf(monkeypatch):
    import os

    import wandb.env
    from wandb.analytics.opentelemetry_proxy import OtelProvider

    monkeypatch.setenv(wandb.env.ERROR_REPORTING, "true")
    with _CaptureServer() as server:
        otel = OtelProvider(endpoint=server.url, pid=os.getpid())
        assert otel._boot()

        otel.record_metric_and_log_event("wandb.test.event", {"foo": "bar"})

        otel._meter_provider.force_flush()
        if otel._logger_provider is not None:
            otel._logger_provider.force_flush()

        # Give the daemon HTTP handler threads a moment to record.
        deadline = time.time() + 5
        while time.time() < deadline and len(server.captured) < 2:
            time.sleep(0.05)

    paths = {path for path, _body, _ct in server.captured}
    assert "/sdk/otel/v1/metrics" in paths
    assert "/sdk/otel/v1/logs" in paths
    for _path, _body, content_type in server.captured:
        assert content_type == "application/json"


def test_proxy_does_not_import_opentelemetry_proto():
    """The analytics package must not pull in the protobuf-bound otel proto."""
    import sys

    # Importing the proxy must not have imported opentelemetry.proto.
    import wandb.analytics.opentelemetry_proxy  # noqa: F401

    assert "opentelemetry.proto" not in sys.modules
