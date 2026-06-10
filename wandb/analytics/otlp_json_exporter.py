"""Serialize OpenTelemetry SDK data to OTLP JSON dicts.

Converts the OpenTelemetry SDK's data into the OTLP/HTTP JSON shape.
This avoids `opentelemetry-proto`, which pins `protobuf<7`.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.sdk.metrics.export import Gauge, Histogram, MetricsData, Sum


def _enum_int(value: Any) -> int:
    """Return the integer value of an Enum or a plain int."""
    return value.value if hasattr(value, "value") else int(value)


def _encode_any_value(value: Any) -> dict[str, Any]:
    """Encode a Python value as an OTLP `AnyValue`."""
    if value is None:
        return {}

    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, bytes):
        return {"bytesValue": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {
            "kvlistValue": {
                "values": [
                    {
                        "key": str(k),
                        "value": _encode_any_value(v),
                    }
                    for k, v in value.items()
                ]
            }
        }
    if isinstance(value, Sequence):
        return {"arrayValue": {"values": [_encode_any_value(v) for v in value]}}

    return {"stringValue": str(value)}


def _encode_attributes(mapping: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not mapping:
        return []

    return [
        {
            "key": str(k),
            "value": _encode_any_value(v),
        }
        for k, v in mapping.items()
    ]


def _encode_resource(resource: Any) -> dict[str, Any]:
    if resource is None:
        return {}
    return {"attributes": _encode_attributes(getattr(resource, "attributes", None))}


def _encode_scope(scope: Any) -> dict[str, Any]:
    if scope is None:
        return {}

    result: dict[str, Any] = {}
    name = getattr(scope, "name", None)
    if name:
        result["name"] = name

    version = getattr(scope, "version", None)
    if version:
        result["version"] = version

    attributes = _encode_attributes(getattr(scope, "attributes", None))
    if attributes:
        result["attributes"] = attributes

    return result


def _encode_number_data_point(dp: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "startTimeUnixNano": str(getattr(dp, "start_time_unix_nano", 0) or 0),
        "timeUnixNano": str(getattr(dp, "time_unix_nano", 0) or 0),
        "attributes": _encode_attributes(getattr(dp, "attributes", None)),
    }

    value = dp.value
    if isinstance(value, bool):
        result["asInt"] = str(int(value))
    elif isinstance(value, int):
        result["asInt"] = str(value)
    else:
        result["asDouble"] = value

    return result


def _encode_histogram_data_point(dp: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "startTimeUnixNano": str(getattr(dp, "start_time_unix_nano", 0) or 0),
        "timeUnixNano": str(getattr(dp, "time_unix_nano", 0) or 0),
        "attributes": _encode_attributes(getattr(dp, "attributes", None)),
        "count": str(getattr(dp, "count", 0) or 0),
        "bucketCounts": [str(c) for c in (getattr(dp, "bucket_counts", None) or [])],
        "explicitBounds": list(getattr(dp, "explicit_bounds", None) or []),
    }

    total = getattr(dp, "sum", None)
    if total is not None:
        result["sum"] = total

    minimum = getattr(dp, "min", None)
    if minimum is not None:
        result["min"] = minimum

    maximum = getattr(dp, "max", None)
    if maximum is not None:
        result["max"] = maximum

    return result


def _encode_metric(metric: Any) -> dict[str, Any] | None:
    result: dict[str, Any] = {"name": metric.name}

    if metric.description:
        result["description"] = metric.description

    if metric.unit:
        result["unit"] = metric.unit

    data = metric.data
    if isinstance(data, Sum):
        result["sum"] = {
            "dataPoints": [_encode_number_data_point(dp) for dp in data.data_points],
            "aggregationTemporality": _enum_int(data.aggregation_temporality),
            "isMonotonic": bool(data.is_monotonic),
        }
    elif isinstance(data, Gauge):
        result["gauge"] = {
            "dataPoints": [_encode_number_data_point(dp) for dp in data.data_points],
        }
    elif isinstance(data, Histogram):
        result["histogram"] = {
            "dataPoints": [_encode_histogram_data_point(dp) for dp in data.data_points],
            "aggregationTemporality": _enum_int(data.aggregation_temporality),
        }
    # Unsupported metric type
    else:
        return None

    return result


def encode_metrics(metrics_data: MetricsData) -> dict[str, Any]:
    """Encode `MetricsData` as an OTLP JSON `ExportMetricsServiceRequest`."""
    resource_metrics: list[dict[str, Any]] = []

    for rm in metrics_data.resource_metrics:
        scope_metrics: list[dict[str, Any]] = []

        for sm in rm.scope_metrics:
            metrics = [
                m for m in (_encode_metric(metric) for metric in sm.metrics) if m
            ]
            if not metrics:
                continue

            entry: dict[str, Any] = {
                "scope": _encode_scope(sm.scope),
                "metrics": metrics,
            }

            schema_url = getattr(sm, "schema_url", None)
            if schema_url:
                entry["schemaUrl"] = schema_url

            scope_metrics.append(entry)

        if not scope_metrics:
            continue

        rentry: dict[str, Any] = {
            "resource": _encode_resource(rm.resource),
            "scopeMetrics": scope_metrics,
        }

        schema_url = getattr(rm, "schema_url", None)
        if schema_url:
            rentry["schemaUrl"] = schema_url

        resource_metrics.append(rentry)

    return {"resourceMetrics": resource_metrics}


def _encode_log_record(record: Any) -> dict[str, Any]:
    """Encode the inner OTel `LogRecord` into an OTLP JSON log record."""
    result: dict[str, Any] = {}

    timestamp = getattr(record, "timestamp", None)
    if timestamp:
        result["timeUnixNano"] = str(timestamp)

    observed = getattr(record, "observed_timestamp", None)
    if observed:
        result["observedTimeUnixNano"] = str(observed)

    severity = getattr(record, "severity_number", None)
    if severity is not None:
        result["severityNumber"] = _enum_int(severity)

    severity_text = getattr(record, "severity_text", None)
    if severity_text:
        result["severityText"] = severity_text

    body = getattr(record, "body", None)
    if body is not None:
        result["body"] = _encode_any_value(body)

    attributes = _encode_attributes(getattr(record, "attributes", None))
    if attributes:
        result["attributes"] = attributes

    trace_id = getattr(record, "trace_id", 0) or 0
    if trace_id:
        result["traceId"] = format(trace_id, "032x")

    span_id = getattr(record, "span_id", 0) or 0
    if span_id:
        result["spanId"] = format(span_id, "016x")

    trace_flags = getattr(record, "trace_flags", 0) or 0
    if trace_flags:
        result["flags"] = int(trace_flags)

    return result


def encode_logs(records: Sequence[Any]) -> dict[str, Any]:
    """Encode a batch of log records as an OTLP JSON ExportLogsServiceRequest."""
    by_resource: dict[int, dict[str, Any]] = {}

    for record in records:
        resource = getattr(record, "resource", None)
        scope = getattr(record, "instrumentation_scope", None)
        inner = getattr(record, "log_record", record)

        resource_group = by_resource.setdefault(
            id(resource), {"resource": resource, "scopes": {}}
        )
        scope_group = resource_group["scopes"].setdefault(
            id(scope), {"scope": scope, "records": []}
        )
        scope_group["records"].append(_encode_log_record(inner))

    resource_logs: list[dict[str, Any]] = []
    for resource_group in by_resource.values():
        scope_logs: list[dict[str, Any]] = []
        for scope_group in resource_group["scopes"].values():
            entry: dict[str, Any] = {
                "scope": _encode_scope(scope_group["scope"]),
                "logRecords": scope_group["records"],
            }
            schema_url = getattr(scope_group["scope"], "schema_url", None)
            if schema_url:
                entry["schemaUrl"] = schema_url
            scope_logs.append(entry)
        resource_logs.append(
            {
                "resource": _encode_resource(resource_group["resource"]),
                "scopeLogs": scope_logs,
            }
        )
    return {"resourceLogs": resource_logs}
