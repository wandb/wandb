"""Serialize OpenTelemetry SDK data to OTLP/JSON dicts.

These helpers convert the in-memory data the OTel SDK hands to an exporter
(``MetricsData`` for metrics, ``ReadableLogRecord`` sequences for logs) into the
JSON shape defined by the OTLP/HTTP protocol's protobuf-to-JSON mapping. Using
JSON lets us avoid the ``opentelemetry-proto`` package, which pins
``protobuf<7`` and would otherwise cap the whole environment's protobuf version.

The encoding follows the OTLP/JSON conventions that trip people up:

* 64-bit integers (timestamps, ``asInt``, counts) are emitted as strings.
* ``trace_id``/``span_id`` are lowercase hex strings.
* Field names are lowerCamelCase.
* Attribute values use the ``AnyValue`` wrapper shape.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.sdk.metrics.export import (
    Gauge,
    Histogram,
    MetricsData,
    Sum,
)


def _enum_int(value: Any) -> int:
    """Return the integer value of an (Int)Enum or a plain int."""
    return value.value if hasattr(value, "value") else int(value)


def _any_value(value: Any) -> dict[str, Any]:
    """Encode a Python value as an OTLP ``AnyValue``."""
    if value is None:
        return {}
    # bool must be checked before int (bool is a subclass of int).
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
                    {"key": str(k), "value": _any_value(v)} for k, v in value.items()
                ]
            }
        }
    if isinstance(value, Sequence):
        return {"arrayValue": {"values": [_any_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _attributes(mapping: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not mapping:
        return []
    return [{"key": str(k), "value": _any_value(v)} for k, v in mapping.items()]


def _resource(resource: Any) -> dict[str, Any]:
    if resource is None:
        return {}
    return {"attributes": _attributes(getattr(resource, "attributes", None))}


def _scope(scope: Any) -> dict[str, Any]:
    if scope is None:
        return {}
    out: dict[str, Any] = {}
    name = getattr(scope, "name", None)
    if name:
        out["name"] = name
    version = getattr(scope, "version", None)
    if version:
        out["version"] = version
    attributes = _attributes(getattr(scope, "attributes", None))
    if attributes:
        out["attributes"] = attributes
    return out


def _number_data_point(dp: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "startTimeUnixNano": str(getattr(dp, "start_time_unix_nano", 0) or 0),
        "timeUnixNano": str(getattr(dp, "time_unix_nano", 0) or 0),
        "attributes": _attributes(getattr(dp, "attributes", None)),
    }
    value = dp.value
    if isinstance(value, bool):
        out["asInt"] = str(int(value))
    elif isinstance(value, int):
        out["asInt"] = str(value)
    else:
        out["asDouble"] = value
    return out


def _histogram_data_point(dp: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "startTimeUnixNano": str(getattr(dp, "start_time_unix_nano", 0) or 0),
        "timeUnixNano": str(getattr(dp, "time_unix_nano", 0) or 0),
        "attributes": _attributes(getattr(dp, "attributes", None)),
        "count": str(getattr(dp, "count", 0) or 0),
        "bucketCounts": [str(c) for c in (getattr(dp, "bucket_counts", None) or [])],
        "explicitBounds": list(getattr(dp, "explicit_bounds", None) or []),
    }
    total = getattr(dp, "sum", None)
    if total is not None:
        out["sum"] = total
    minimum = getattr(dp, "min", None)
    if minimum is not None:
        out["min"] = minimum
    maximum = getattr(dp, "max", None)
    if maximum is not None:
        out["max"] = maximum
    return out


def _metric(metric: Any) -> dict[str, Any] | None:
    out: dict[str, Any] = {"name": metric.name}
    if metric.description:
        out["description"] = metric.description
    if metric.unit:
        out["unit"] = metric.unit

    data = metric.data
    if isinstance(data, Sum):
        out["sum"] = {
            "dataPoints": [_number_data_point(dp) for dp in data.data_points],
            "aggregationTemporality": _enum_int(data.aggregation_temporality),
            "isMonotonic": bool(data.is_monotonic),
        }
    elif isinstance(data, Gauge):
        out["gauge"] = {
            "dataPoints": [_number_data_point(dp) for dp in data.data_points],
        }
    elif isinstance(data, Histogram):
        out["histogram"] = {
            "dataPoints": [_histogram_data_point(dp) for dp in data.data_points],
            "aggregationTemporality": _enum_int(data.aggregation_temporality),
        }
    else:
        # Unsupported metric type (e.g. exponential histogram); skip it rather
        # than emit an invalid payload.
        return None
    return out


def encode_metrics(metrics_data: MetricsData) -> dict[str, Any]:
    """Encode ``MetricsData`` as an OTLP/JSON ExportMetricsServiceRequest."""
    resource_metrics: list[dict[str, Any]] = []
    for rm in metrics_data.resource_metrics:
        scope_metrics: list[dict[str, Any]] = []
        for sm in rm.scope_metrics:
            metrics = [m for m in (_metric(metric) for metric in sm.metrics) if m]
            if not metrics:
                continue
            entry: dict[str, Any] = {"scope": _scope(sm.scope), "metrics": metrics}
            schema_url = getattr(sm, "schema_url", None)
            if schema_url:
                entry["schemaUrl"] = schema_url
            scope_metrics.append(entry)
        if not scope_metrics:
            continue
        rentry: dict[str, Any] = {
            "resource": _resource(rm.resource),
            "scopeMetrics": scope_metrics,
        }
        schema_url = getattr(rm, "schema_url", None)
        if schema_url:
            rentry["schemaUrl"] = schema_url
        resource_metrics.append(rentry)
    return {"resourceMetrics": resource_metrics}


def _log_record(record: Any) -> dict[str, Any]:
    """Encode the inner OTel LogRecord into an OTLP/JSON log record."""
    out: dict[str, Any] = {}

    timestamp = getattr(record, "timestamp", None)
    if timestamp:
        out["timeUnixNano"] = str(timestamp)
    observed = getattr(record, "observed_timestamp", None)
    if observed:
        out["observedTimeUnixNano"] = str(observed)

    severity = getattr(record, "severity_number", None)
    if severity is not None:
        out["severityNumber"] = _enum_int(severity)
    severity_text = getattr(record, "severity_text", None)
    if severity_text:
        out["severityText"] = severity_text

    body = getattr(record, "body", None)
    if body is not None:
        out["body"] = _any_value(body)

    attributes = _attributes(getattr(record, "attributes", None))
    if attributes:
        out["attributes"] = attributes

    trace_id = getattr(record, "trace_id", 0) or 0
    if trace_id:
        out["traceId"] = format(trace_id, "032x")
    span_id = getattr(record, "span_id", 0) or 0
    if span_id:
        out["spanId"] = format(span_id, "016x")
    trace_flags = getattr(record, "trace_flags", 0) or 0
    if trace_flags:
        out["flags"] = int(trace_flags)

    return out


def encode_logs(records: Sequence[Any]) -> dict[str, Any]:
    """Encode a batch of log records as an OTLP/JSON ExportLogsServiceRequest.

    Accepts the SDK's ``ReadableLogRecord`` (which wraps the data in
    ``.log_record`` and exposes ``.resource``/``.instrumentation_scope``) as
    well as older ``LogData``-style objects.
    """
    # Group by resource, then by instrumentation scope, preserving order.
    resource_order: list[int] = []
    by_resource: dict[int, dict[str, Any]] = {}

    for record in records:
        resource = getattr(record, "resource", None)
        scope = getattr(record, "instrumentation_scope", None)
        inner = getattr(record, "log_record", record)

        rid = id(resource)
        if rid not in by_resource:
            by_resource[rid] = {"resource": resource, "scopes": {}, "order": []}
            resource_order.append(rid)
        rgroup = by_resource[rid]

        sid = id(scope)
        if sid not in rgroup["scopes"]:
            rgroup["scopes"][sid] = {"scope": scope, "records": []}
            rgroup["order"].append(sid)
        rgroup["scopes"][sid]["records"].append(_log_record(inner))

    resource_logs: list[dict[str, Any]] = []
    for rid in resource_order:
        rgroup = by_resource[rid]
        scope_logs: list[dict[str, Any]] = []
        for sid in rgroup["order"]:
            sgroup = rgroup["scopes"][sid]
            entry: dict[str, Any] = {
                "scope": _scope(sgroup["scope"]),
                "logRecords": sgroup["records"],
            }
            schema_url = getattr(sgroup["scope"], "schema_url", None)
            if schema_url:
                entry["schemaUrl"] = schema_url
            scope_logs.append(entry)
        resource_logs.append(
            {
                "resource": _resource(rgroup["resource"]),
                "scopeLogs": scope_logs,
            }
        )
    return {"resourceLogs": resource_logs}
