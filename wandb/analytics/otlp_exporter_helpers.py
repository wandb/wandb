"""Custom OTLP JSON exporters that avoid the OTLP protobuf packages.

The official `opentelemetry-exporter-otlp-proto-*` exporters depend on
`opentelemetry-proto`, which pins `protobuf<7`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar

from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

from ._otlp_json import encode_logs, encode_metrics

if TYPE_CHECKING:
    import requests
    from opentelemetry.sdk.metrics.export import AggregationTemporality, MetricsData
    from opentelemetry.sdk.metrics.view import Aggregation

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class _JSONHTTPExporter:
    """Shared OTLP JSON exporter for metrics and logs."""

    _endpoint: str
    _session: requests.Session
    _timeout: float

    def _export(
        self,
        payload: dict[str, Any],
        payload_key: str,
        success: _T,
        failure: _T,
    ) -> _T:
        """Encode-and-POST a payload, mapping the outcome to an SDK result enum.

        An empty payload counts as success (nothing to send).
        Any exception is logged as debug so telemetry never crashes the caller.
        """
        try:
            if not payload.get(payload_key):
                return success
            response = self._session.post(
                self._endpoint, json=payload, timeout=self._timeout
            )
            return success if response.status_code // 100 == 2 else failure
        except Exception:
            _logger.debug("otel export to %s failed", self._endpoint, exc_info=True)
            return failure


class JSONMetricExporter(_JSONHTTPExporter, MetricExporter):
    """Exports metrics as OTLP JSON over HTTP."""

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
        timeout_millis: float = 1_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        return self._export(
            encode_metrics(metrics_data),
            "resourceMetrics",
            MetricExportResult.SUCCESS,
            MetricExportResult.FAILURE,
        )

    def force_flush(self, timeout_millis: float = 1_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 1_000, **kwargs: Any) -> None:
        return None


class JSONLogExporter(_JSONHTTPExporter, LogRecordExporter):
    """Exports log records as OTLP JSON over HTTP."""

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
        return self._export(
            encode_logs(batch),
            "resourceLogs",
            LogRecordExportResult.SUCCESS,
            LogRecordExportResult.FAILURE,
        )

    def shutdown(self) -> None:
        return None
