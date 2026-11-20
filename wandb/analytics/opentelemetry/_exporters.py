"""OTLP exporters that hand each encoded batch to a send function once.

The OpenTelemetry OTLP/HTTP exporters draw retry jitter from the global
`random` generator on every export, which changes the numbers a seeded script
gets from `random`. These exporters do not retry: a batch that is not accepted
is dropped.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from opentelemetry.exporter.otlp.proto.common._log_encoder import encode_logs
from opentelemetry.exporter.otlp.proto.common.metrics_encoder import encode_metrics
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.metrics import Counter, Histogram
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    MetricExporter,
    MetricExportResult,
    MetricsData,
)


class OnceMetricExporter(MetricExporter):
    def __init__(self, send: Callable[[bytes], bool]) -> None:
        super().__init__(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            },
        )
        self._send = send

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        if self._send(encode_metrics(metrics_data).SerializeToString()):
            return MetricExportResult.SUCCESS
        return MetricExportResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        pass


class OnceLogExporter(LogRecordExporter):
    def __init__(self, send: Callable[[bytes], bool]) -> None:
        self._send = send

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        if self._send(encode_logs(batch).SerializeToString()):
            return LogRecordExportResult.SUCCESS
        return LogRecordExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def shutdown(self) -> None:
        pass
