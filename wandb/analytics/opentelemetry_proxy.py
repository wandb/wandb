from __future__ import annotations

import functools
import logging
import os
import platform
import sys
import threading
import traceback
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

_OTEL_SERVICE_NAME = "wandb-sdk"
_DEFAULT_ENDPOINT = "https://api.wandb.ai"
_DEFAULT_EXPORT_INTERVAL_MS = 500

# TODO: revisit this timeout and verify failure mode, e.g. server not reachable
# Per-request HTTP timeout for the OTLP exporters, in seconds. Analytics
# telemetry should never block the user's thread on a slow or unreachable
# collector, so we fail fast.
_OTLP_HTTP_TIMEOUT_SECONDS = 1


class LowCardinalityAttributes(TypedDict, total=False):
    """Allow-list of low-cardinality attributes emitted as metric dimensions.

    Each declared field corresponds to a tag whose value MUST come from a
    small, bounded set.
    """

    python_runtime: str
    wandb_version: str
    python_version: str


_ALLOWED_LOW_CARDINALITY_KEYS: frozenset[str] = frozenset(
    LowCardinalityAttributes.__annotations__,
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
        # do nothing; get_otel() will create a fresh instance for the child.
        if self._pid != os.getpid():
            return None

        if not self._booted and not self._boot():
            return None

        return func(self, *args, **kwargs)

    return wrapper


class TelemetryContext:
    """Contains persistent attributes added to all telemetry records.

    Tags are split into two buckets:
    - `low_cardinality_attributes`: a small, bounded set of values (e.g.
      `wandb_version`, `python_version`).
      These are restricted to a known set of keys,
      to avoid creating too many metrics dimensions.
    - `high_cardinality_attributes`: unbounded set of values.
       These are attached to log records where high cardinality is acceptable.

    The context is mutated over the lifetime of a provider via
    `add_low_cardinality_tags` / `add_high_cardinality_tags` (typically
    through `OtelProvider.configure_scope`) and read back when records are
    emitted.
    """

    def __init__(self) -> None:
        from wandb import __version__

        self.tags: dict[str, str] = {}
        self.low_cardinality_attributes: dict[str, str] = {
            "wandb_version": __version__,
            "python_version": platform.python_version(),
        }
        self.high_cardinality_attributes: dict[str, str] = {}

    def add_low_cardinality_attributes(
        self,
        attributes: LowCardinalityAttributes,
    ) -> None:
        """Merge caller-supplied low-cardinality tags into the scope.

        Only keys declared on `LowCardinalityAttributes` are accepted; any other
        keys are silently dropped.
        """
        for key, value in attributes.items():
            if key in _ALLOWED_LOW_CARDINALITY_KEYS and isinstance(value, str):
                self.low_cardinality_attributes[key] = value

    def add_high_cardinality_attributes(
        self,
        attributes: dict[str, str],
    ) -> None:
        self.high_cardinality_attributes.update(attributes)


class OtelProvider:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        pid: int,
    ) -> None:
        from wandb import env as _env

        self._enabled = bool(_env.error_reporting_enabled())
        self._pid = pid
        self.scope = TelemetryContext()

        if endpoint is None:
            endpoint = os.environ.get(_env.TELEMETRY_ENDPOINT, _DEFAULT_ENDPOINT)
        self._base_url = endpoint.rstrip("/") + "/sdk/otel/v1"

        self._booted = False
        self._boot_lock = threading.Lock()
        self._meter: metrics.Meter | None = None
        self._logger_provider: LoggerProvider | None = None
        self._logger: OTelLogger | None = None

    def _boot(
        self,
        export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    ) -> bool:
        """Initialize the OTel providers.

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
                resource = Resource.create({"service.name": _OTEL_SERVICE_NAME})

                # Custom OTLP/JSON exporters keep the OTel SDK protobuf-free;
                # see wandb/analytics/_otlp_exporters.py.
                session = requests.Session()

                # Setup metrics exporter
                metric_exporter = JSONMetricExporter(
                    endpoint=f"{self._base_url}/metrics",
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
                    endpoint=f"{self._base_url}/logs",
                    session=session,
                    timeout=_OTLP_HTTP_TIMEOUT_SECONDS,
                )
                self._logger_provider = LoggerProvider(resource=resource)
                self._logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(log_exporter),
                )
                self._logger = self._logger_provider.get_logger("wandb.sdk")

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
    def configure_context(
        self,
        low_cardinality_attrs: LowCardinalityAttributes,
        high_cardinality_attrs: dict[str, str],
    ) -> None:
        self.scope.add_low_cardinality_attributes(low_cardinality_attrs)
        self.scope.add_high_cardinality_attributes(high_cardinality_attrs)

    @_guard
    def _record_count(
        self,
        name: str,
    ) -> None:
        """Increment a counter metric with the given name by 1.

        Only low-cardinality attributes from the current context are
        included in the metric record.
        """
        assert self._meter is not None

        counter = self._meter.create_counter(name, unit="Count")
        counter.add(1, attributes=self.scope.low_cardinality_attributes)

    @_guard
    def record_log(
        self,
        message: str,
        attributes: dict[str, str] | None = None,
        severity: SeverityNumber = SeverityNumber.INFO,
    ) -> None:
        """Emit an OpenTelemetry log record with the specified severity level.

        The log record contains the attributes from the current context,
        in addition to the attributes passed when this method is called.
        """
        assert self._logger is not None

        merged_attributes = {
            **self.scope.low_cardinality_attributes,
            **self.scope.high_cardinality_attributes,
            **(attributes or {}),
        }
        self._logger.emit(
            body=message,
            severity_number=severity,
            attributes=merged_attributes,
        )

    @_guard
    def record_metric_and_log_event(
        self,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Record a counter metric and a log event with the given name."""
        self._record_count(name)

        self.record_log(
            message=name,
            attributes=attributes,
        )

    @_guard
    def exception(
        self,
        message: str,
        exc: Exception,
    ) -> None:
        """Record an exception as both a counter metric and an error log.

        The counter metric has the name "exception" and contains
        the low-cardinality attributes from the current context plus an
        "exception.type" dimension (the exception's class name) so the
        rate of each exception class can be aggregated and graphed.

        The log record contains the attributes from the current context,
        plus "exception.type", "exception.message", and
        "exception.stacktrace" attributes.

        Args:
            message: The body for the log record.
            exc: The exception the occurred.
        """
        self._record_count(
            name="exception",
        )

        exception_attributes = {
            "exception.type": type(exc).__name__,
            "exception.stacktrace": _exception_stacktrace(exc),
            **self.scope.low_cardinality_attributes,
            **self.scope.high_cardinality_attributes,
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


def _exception_stacktrace(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))