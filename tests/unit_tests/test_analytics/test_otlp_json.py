from __future__ import annotations

import time

import pytest
from wandb.analytics.opentelemetry import otlp_json_helpers as _otlp_json


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
            {
                "arrayValue": {
                    "values": [{"intValue": "1"}, {"stringValue": "a"}],
                }
            },
        ),
        (
            {"k": 2},
            {
                "kvlistValue": {
                    "values": [{"key": "k", "value": {"intValue": "2"}}],
                }
            },
        ),
    ],
)
def test_any_value_encoding(value, expected):
    assert _otlp_json._encode_any_value(value) == expected


def test_attributes_encoding():
    assert _otlp_json._encode_attributes({"a": "x", "n": 3}) == [
        {"key": "a", "value": {"stringValue": "x"}},
        {"key": "n", "value": {"intValue": "3"}},
    ]


def test_encode_metrics():
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
    counter.add(3, attributes={"test": "test_attribute"})

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    payload = _otlp_json.encode_metrics(metrics_data)

    metric = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
    assert metric["name"] == "my_counter"

    sum_data = metric["sum"]
    assert sum_data["isMonotonic"] is True
    assert sum_data["aggregationTemporality"] == AggregationTemporality.DELTA.value

    dp = sum_data["dataPoints"][0]
    assert dp["asInt"] == "3"
    assert isinstance(dp["timeUnixNano"], str)
    assert dp["attributes"] == [
        {
            "key": "test",
            "value": {"stringValue": "test_attribute"},
        }
    ]


def test_encode_logs():
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        LogRecordExporter,
        LogRecordExportResult,
        SimpleLogRecordProcessor,
    )

    captured: list = []

    class CapturingLogExporter(LogRecordExporter):
        def export(self, batch):
            captured.extend(batch)
            return LogRecordExportResult.SUCCESS

        def shutdown(self):
            pass

    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(CapturingLogExporter()))
    provider.get_logger("test").emit(
        body="test_log",
        severity_number=SeverityNumber.ERROR,
        attributes={"test": "test_attribute"},
    )
    provider.force_flush()

    payload = _otlp_json.encode_logs(captured)
    record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["body"] == {"stringValue": "test_log"}
    assert record["severityNumber"] == SeverityNumber.ERROR.value
    assert record["attributes"] == [
        {
            "key": "test",
            "value": {"stringValue": "test_attribute"},
        }
    ]


def test_proxy_emits_otlp(monkeypatch, capture_server):
    import os

    import wandb.env
    from wandb.analytics.opentelemetry.opentelemetry_proxy import OtelProvider

    monkeypatch.setenv(wandb.env.ERROR_REPORTING, "true")
    otel = OtelProvider(endpoint=capture_server.url, pid=os.getpid())

    otel.record_metric_and_log_event("wandb.test.event", {"foo": "bar"})
    otel._meter_provider.force_flush()
    otel._logger_provider.force_flush()
    deadline = time.time() + 1
    while time.time() < deadline and len(capture_server.captured) < 2:
        time.sleep(0.05)

    paths = capture_server.captured_paths
    assert "/sdk/otel/v1/metrics" in paths
    assert "/sdk/otel/v1/logs" in paths
    for _path, _body, content_type in capture_server.captured:
        assert content_type == "application/json"
