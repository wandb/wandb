"""Custom OTLP/JSON exporters that avoid the protobuf-bound OTLP packages.

The official ``opentelemetry-exporter-otlp-proto-*`` exporters serialize through
``opentelemetry-proto``, which pins ``protobuf<7``. These exporters instead
serialize the SDK's in-memory data to OTLP/JSON (see :mod:`._otlp_json`) and
POST it over plain HTTP, so the OpenTelemetry SDK can be used without
constraining the environment's protobuf version.

They plug into the standard SDK machinery: the metric exporter is driven by a
``PeriodicExportingMetricReader`` and the log exporter by a
``BatchLogRecordProcessor``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry.sdk._logs.export import LogExporter
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

from ._otlp_json import encode_logs, encode_metrics

if TYPE_CHECKING:
    import requests
    from opentelemetry.sdk.metrics.export import AggregationTemporality, MetricsData
    from opentelemetry.sdk.metrics.view import Aggregation

_logger = logging.getLogger(__name__)

# The SDK renamed the log export result enum across versions; accept either.
try:
    from opentelemetry.sdk._logs.export import (
        LogRecordExportResult as _LogResult,  # type: ignore[attr-defined]
    )
except ImportError:  # pragma: no cover - depends on SDK version
    from opentelemetry.sdk._logs.export import (
        LogExportResult as _LogResult,  # type: ignore[attr-defined]
    )


def _post_json(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> bool:
    """POST an OTLP/JSON payload. Returns True on a 2xx response."""
    response = session.post(url, json=payload, timeout=timeout)
    return response.status_code // 100 == 2


class JSONMetricExporter(MetricExporter):
    """Exports metrics as OTLP/JSON over HTTP."""

    def __init__(
        self,
        endpoint: str,
        session: requests.Session,
        timeout: float,
        preferred_temporality: dict[type, AggregationTemporality] | None = None,
        preferred_aggregation: dict[type, Aggregation] | None = None,
    ) -> None:
        super().__init__(
            preferred_temporality=preferred_temporality,
            preferred_aggregation=preferred_aggregation,
        )
        self._endpoint = endpoint
        self._session = session
        self._timeout = timeout

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        try:
            payload = encode_metrics(metrics_data)
            if not payload.get("resourceMetrics"):
                return MetricExportResult.SUCCESS
            if _post_json(self._session, self._endpoint, payload, self._timeout):
                return MetricExportResult.SUCCESS
            else:
                return MetricExportResult.FAILURE
        except Exception:
            _logger.debug("otel metric export failed", exc_info=True)
            return MetricExportResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        return None


class JSONLogExporter(LogExporter):
    """Exports log records as OTLP/JSON over HTTP."""

    def __init__(
        self,
        endpoint: str,
        session: requests.Session,
        timeout: float,
    ) -> None:
        self._endpoint = endpoint
        self._session = session
        self._timeout = timeout

    def export(self, batch: Any) -> Any:
        try:
            payload = encode_logs(batch)
            if not payload.get("resourceLogs"):
                return _LogResult.SUCCESS
            if _post_json(self._session, self._endpoint, payload, self._timeout):
                return _LogResult.SUCCESS
            else:
                return _LogResult.FAILURE
        except Exception:
            _logger.debug("otel log export failed", exc_info=True)
            return _LogResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self) -> None:
        return None
