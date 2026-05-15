from __future__ import annotations

import functools
import logging
import os
import platform
import sys
import threading
from collections.abc import Callable
from typing import Any, Concatenate, ParamSpec, TypedDict, TypeVar

import requests
from opentelemetry import metrics
from opentelemetry._logs import Logger as OTelLogger
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider, UpDownCounter
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from typing_extensions import Never

from ._otlp_exporters import JSONLogExporter, JSONMetricExporter

_P = ParamSpec("_P")
_R = TypeVar("_R")

_logger = logging.getLogger(__name__)

# TODO: change this to the production endpoint before PR
_DEFAULT_ENDPOINT = "https://api.wandb.test"
_DEFAULT_EXPORT_INTERVAL_MS = 500

# Per-request HTTP timeout for the OTLP exporters, in seconds. Analytics
# telemetry should never block the user's thread on a slow or unreachable
# collector, so we fail fast.
_OTLP_HTTP_TIMEOUT_SECONDS = 1


class LowCardinalityTags(TypedDict, total=False):
    """Allow-list of low-cardinality tags emitted as metric dimensions.

    Each declared field corresponds to a tag whose value MUST come from a
    small, bounded set (e.g. an enum-like string). High-cardinality values
    (user IDs, run IDs, free-form messages) belong on log records, not here.

    To declare a new allowed tag, add a single typed field below. Type
    checkers will then accept the new key at every call site of
    `Scope.add_low_cardinality_tags` and reject typos / undeclared keys,
    while the runtime filter `_ALLOWED_LOW_CARDINALITY_KEYS` picks it up
    automatically.
    """

    python_runtime: str
    wandb_version: str
    python_version: str


_ALLOWED_LOW_CARDINALITY_KEYS: frozenset[str] = frozenset(
    LowCardinalityTags.__annotations__,
)


def _guard(
    func: Callable[Concatenate[OtelProvider, _P], _R],
) -> Callable[Concatenate[OtelProvider, _P], _R]:
    @functools.wraps(func)
    def wrapper(
        self: OtelProvider,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not self._enabled:
            return None

        # If this instance belongs to a different process (fork happened),
        # do nothing; get_sentry() will create a fresh instance for the child.
        if self._pid != os.getpid():
            return None

        if not self._booted and not self._boot():
            return None

        return func(self, *args, **kwargs)

    return wrapper


def _shutdown(
    meter_provider: MeterProvider,
    logger_provider: LoggerProvider,
) -> None:
    if meter_provider is not None:
        meter_provider.force_flush()
        meter_provider.shutdown()

    if logger_provider is not None:
        logger_provider.force_flush()
        logger_provider.shutdown()


class Scope:
    def __init__(self) -> None:
        from wandb import __version__

        self.tags: dict[str, str] = {}
        self.low_cardinality_tags: dict[str, str] = {
            "wandb_version": __version__,
            "python_version": platform.python_version(),
        }
        self.high_cardinality_tags: dict[str, Any] = {}

    def add_low_cardinality_tags(self, tags: LowCardinalityTags | None) -> None:
        """Merge caller-supplied low-cardinality tags into the scope.

        Only keys declared on `LowCardinalityTags` are accepted; any other
        keys are silently dropped to keep metric cardinality bounded. To
        permit a new key, add a field to `LowCardinalityTags`.
        """
        if tags is None:
            return

        for key, value in tags.items():
            if key in _ALLOWED_LOW_CARDINALITY_KEYS and isinstance(value, str):
                self.low_cardinality_tags[key] = value

    def add_high_cardinality_tags(self, tags: dict[str, Any] | None) -> None:
        if tags is None:
            return

        self.high_cardinality_tags.update(tags)


class OtelProvider:
    def __init__(
        self,
        *,
        pid: int,
    ) -> None:
        from wandb import env as _env

        # self._enabled = bool(_env.error_reporting_enabled())
        self._enabled = True
        self._pid = pid
        self.scope = Scope()

        self._booted = False
        self._boot_lock = threading.Lock()
        self._meter: metrics.Meter | None = None
        self._logger_provider: LoggerProvider | None = None
        self._logger: OTelLogger | None = None
        self._base_url: str = _DEFAULT_ENDPOINT

    def _boot(
        self,
        endpoint: str = _DEFAULT_ENDPOINT,
        export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    ) -> bool:
        """Initialize the OTel MeterProvider and LoggerProvider.

        Safe to call multiple times. Returns True if the providers are
        ready (already-booted or just-booted now), False if initialization
        failed.
        """
        with self._boot_lock:
            if not self._enabled:
                return False

            if self._booted:
                return True

            try:
                base_url = endpoint.rstrip("/")
                resource = Resource.create({"service.name": "wandb-sdk"})

                # Custom OTLP/JSON exporters keep the OTel SDK protobuf-free;
                # see wandb/analytics/_otlp_exporters.py.
                session = requests.Session()

                # Setup metrics exporter
                metric_exporter = JSONMetricExporter(
                    endpoint=f"{base_url}/sdk/otel/v1/metrics",
                    session=session,
                    timeout=_OTLP_HTTP_TIMEOUT_SECONDS,
                    preferred_temporality={
                        Counter: AggregationTemporality.DELTA,
                        UpDownCounter: AggregationTemporality.DELTA,
                        Histogram: AggregationTemporality.DELTA,
                    },
                )
                reader = PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=export_interval_ms,
                )
                self._provider = MeterProvider(
                    resource=resource,
                    metric_readers=[reader],
                )
                self._meter = self._provider.get_meter("wandb.sdk")

                # Setup logs exporter
                log_exporter = JSONLogExporter(
                    endpoint=f"{base_url}/sdk/otel/v1/logs",
                    session=session,
                    timeout=_OTLP_HTTP_TIMEOUT_SECONDS,
                )
                self._logger_provider = LoggerProvider(resource=resource)
                self._logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(log_exporter),
                )
                self._logger = self._logger_provider.get_logger("wandb.sdk")
                self._base_url = base_url
                self._booted = True

                return True
            except Exception:
                _logger.debug("OtelProvider boot failed", exc_info=True)
                self._enabled = False
                self._booted = False
                self._meter = None
                self._logger = None
                self._logger_provider = None
                return False

    @_guard
    def configure_scope(
        self,
        low_cardinality_tags: LowCardinalityTags | None = None,
        high_cardinality_tags: dict[str, Any] | None = None,
    ) -> None:
        self.scope.add_low_cardinality_tags(low_cardinality_tags)
        self.scope.add_high_cardinality_tags(high_cardinality_tags)

    @_guard
    def _record_count(
        self,
        name: str,
    ) -> None:
        """Increment a counter metric with the given name.

        Only low-cardinality tags from the current scope are included in the metric record.
        Call `record_log` to emit a log record with higher cardinality attributes.
        """
        assert self._meter is not None
        counter = self._meter.create_counter(name, unit="Count")
        counter.add(1, attributes=self.scope.low_cardinality_tags)

    @_guard
    def record_log(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        severity: SeverityNumber = SeverityNumber.INFO,
    ) -> None:
        """Emit an OTel log record.

        The log record contains the high-cardinality attributes from the current scope,
        in addition to the attributes passed when this method is called.

        Use this for detailed event data (user IDs, run IDs, file paths, etc.)
        that would be too high-cardinality for metric tags.
        """
        assert self._logger is not None
        self._logger.emit(
            body=name,
            severity_number=severity,
            attributes=attributes,
        )

    @_guard
    def record_metric_and_log_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a metric and a log event with the given name.

        The metric record contains the low-cardinality attributes from the current scope.
        While the log record contains the high-cardinality attributes from the current scope,
        in addition to the attributes passed when this method is called.
        """
        assert self._logger is not None
        self._record_count(name)

        merged_attributes = {
            **self.scope.high_cardinality_tags,
            **(attributes or {}),
        }
        self.record_log(
            name=name,
            attributes=merged_attributes,
        )

    @_guard
    def exception(
        self,
        message: str,
        exc: Exception,
    ) -> None:
        """Record an exception as both a counter metric and an error log.

        Emits two signals:

        - A counter metric named `"exception"` incremented by one. The
          counter carries the scope's low-cardinality tags plus an
          `exception.type` dimension (the exception's class name) so the
          rate of each exception class can be aggregated and graphed.
        - An OTel log record at `SeverityNumber.ERROR` whose body is
          `message`. The record carries `exception.type`,
          `exception.message` (the stringified exception), and the
          scope's high-cardinality tags as attributes for drill-down.

        Args:
            message: Human-readable description of where/why the
                exception was caught. This becomes the log record body.
            exc: The exception instance. Its class name is used as the
                low-cardinality `exception.type` dimension.
        """
        self._record_count(
            name="exception",
        )

        exception_attributes = {
            "exception.type": type(exc).__name__,
            **self.scope.high_cardinality_tags,
        }
        self.record_log(
            message,
            severity=SeverityNumber.ERROR,
            attributes=exception_attributes,
        )

    @_guard
    def reraise(self, exc: Exception) -> Never:
        """Re-raise after logging an exception, preserving traceback."""
        try:
            self.exception(str(exc), exc)
        finally:
            _, _, tb = sys.exc_info()
            if tb is not None and hasattr(exc, "with_traceback"):
                raise exc.with_traceback(tb)
            raise exc


_singleton: OtelProvider | None = None
_singleton_lock = threading.Lock()


def get_otel() -> OtelProvider:
    global _singleton
    pid = os.getpid()
    with _singleton_lock:
        if _singleton is not None and _singleton._pid == pid:
            return _singleton
        if _singleton is None or _singleton._pid != pid:
            _singleton = OtelProvider(pid=pid)
        return _singleton
