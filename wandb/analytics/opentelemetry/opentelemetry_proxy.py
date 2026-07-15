from __future__ import annotations

import contextlib
import functools
import logging
import os
import platform
import threading
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypedDict, TypeVar

import requests
from opentelemetry._logs import Logger, NoOpLogger, SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Counter, Meter, NoOpMeter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from requests import auth as requests_auth
from typing_extensions import Never

from wandb import env

_P = ParamSpec("_P")
_R = TypeVar("_R")

_logger = logging.getLogger(__name__)

_OTEL_SERVICE_NAME = "wandb-sdk"
_DEFAULT_ENDPOINT = "https://api.wandb.ai"
_DEFAULT_EXPORT_INTERVAL_MS = 500
_OTLP_HTTP_EXPORTER_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http._log_exporter",
    "opentelemetry.exporter.otlp.proto.http.metric_exporter",
)

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
    func: Callable[Concatenate[TelemetryRecorder, _P], _R | None],
) -> Callable[Concatenate[TelemetryRecorder, _P], _R | None]:
    """Gates `TelemetryRecorder` methods so they only run when it is safe to.

    A recorder is safe to use when:
    - Telemetry is enabled.
    - The recorder's root provider belongs to the current process.
    """

    @functools.wraps(func)
    def wrapper(
        self: TelemetryRecorder,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R | None:
        root = self._root
        if not root._enabled:
            return None

        # If the root belongs to a different process (e.g. fork happened),
        # do nothing; get_otel() will create a fresh instance for the child.
        if root._pid != os.getpid():
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

    A context is never mutated in place. New attributes are layered on via
    `with_attributes`, which returns a derived child context; the parent is
    left unchanged. Contexts are read back when records are emitted.
    """

    def __init__(self) -> None:
        from wandb import __version__

        self.low_cardinality_attributes: dict[str, str] = {
            "wandb_version": __version__,
            "python_version": platform.python_version(),
        }
        self.high_cardinality_attributes: dict[str, str] = {}

    def copy(self) -> TelemetryContext:
        """Return a shallow copy of this context with independent attributes.

        The returned context has its own attribute dicts, so mutating them does
        not affect this context.
        """
        clone = TelemetryContext()
        clone.low_cardinality_attributes = dict(self.low_cardinality_attributes)
        clone.high_cardinality_attributes = dict(self.high_cardinality_attributes)
        return clone

    def with_attributes(
        self,
        low_cardinality_attributes: LowCardinalityAttributes,
        high_cardinality_attributes: dict[str, str],
    ) -> TelemetryContext:
        """Return a child context that inherits this context's attributes.

        The child's attributes are this context's attributes merged with the
        supplied ones. When the same attribute is present in both,
        the provided attributes take precedence.
        This context is not modified,
        so attributes added to the child never leak back onto the parent.

        Only low-cardinality keys declared on `LowCardinalityAttributes` are
        accepted; any other keys are silently dropped.
        """
        child = self.copy()

        for key, value in low_cardinality_attributes.items():
            if key in _ALLOWED_LOW_CARDINALITY_KEYS and isinstance(value, str):
                child.low_cardinality_attributes[key] = value
        child.high_cardinality_attributes.update(high_cardinality_attributes)

        return child


class TelemetryRecorder(ABC):
    """Records OpenTelemetry events (metrics and logs).

    Recorders form a hierarchy: `with_context` derives a child recorder with
    additional attributes. Child recorders share the root provider's
    OpenTelemetry providers, and therefore do not need to be shut down.
    """

    _context: TelemetryContext

    @property
    @abstractmethod
    def _root(self) -> OtelProvider:
        """The root provider that owns the OpenTelemetry providers."""

    def with_context(
        self,
        low_cardinality_attributes: LowCardinalityAttributes | None = None,
        high_cardinality_attributes: dict[str, str] | None = None,
    ) -> TelemetryRecorder:
        """Return a derived recorder with additional attributes.

        The derived recorder shares this recorder's root providers but carries
        a child telemetry context that inherits this recorder's attributes
        merged with the supplied ones. This recorder is unchanged: attributes
        added to the derived recorder never appear on records emitted through
        this recorder or its siblings.
        """
        return _ChildRecorder(
            self._root,
            self._context.with_attributes(
                low_cardinality_attributes or {},
                high_cardinality_attributes or {},
            ),
        )

    @_guard
    def _increment_counter(
        self,
        name: str,
    ) -> None:
        """Increment a counter metric with the given name by 1.

        Only low-cardinality attributes from the current context are
        included in the metric record.
        """
        root = self._root

        low_cardinality_attributes = dict(self._context.low_cardinality_attributes)

        counter = root._counters.get(name)
        if counter is None:
            with root._counters_lock:
                counter = root._counters.get(name)
                if counter is None:
                    counter = root._meter.create_counter(name, unit="Count")
                    root._counters[name] = counter

        counter.add(1, attributes=low_cardinality_attributes)

    @_guard
    def log(
        self,
        message: str,
        attributes: dict[str, str] | None = None,
        severity: SeverityNumber = SeverityNumber.INFO,
    ) -> None:
        """Emit an OpenTelemetry log record with the specified severity level.

        The log record contains the attributes from the current context,
        in addition to the attributes passed when this method is called.
        """
        root = self._root

        merged_attributes = {
            **self._context.low_cardinality_attributes,
            **self._context.high_cardinality_attributes,
            **(attributes or {}),
        }
        root._logger.emit(
            body=message,
            severity_number=severity,
            attributes=merged_attributes,
        )

    @_guard
    def increment_counter_and_log_event(
        self,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter metric by 1 and log an event with the given name."""
        self._increment_counter(name)
        self.log(
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
        self._increment_counter(
            name="exception",
        )

        exception_attributes = {
            "exception.type": type(exc).__name__,
            "exception.stacktrace": _exception_stacktrace(exc),
            **self._context.low_cardinality_attributes,
            **self._context.high_cardinality_attributes,
        }
        self.log(
            message,
            severity=SeverityNumber.ERROR,
            attributes=exception_attributes,
        )

    def reraise(self, exc: Exception) -> Never:
        """Log the exception to telemetry, then re-raise it."""
        with contextlib.suppress(Exception):
            self.exception(str(exc), exc)
        raise exc


class OtelProvider(TelemetryRecorder):
    """The root `TelemetryRecorder`, which owns the OpenTelemetry providers.

    The root is responsible for initializing and shutting down the underlying
    providers. Child recorders derived via `with_context` share these providers
    but do not own them.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str,
        pid: int | None = None,
    ) -> None:
        self._enabled = bool(env.error_reporting_enabled())
        self._pid = pid or os.getpid()
        self._api_key = api_key
        self._context = TelemetryContext()
        self._session: requests.Session = requests.Session()

        # Counters should be created only once per name,
        # so we cache the counter object upon creation.
        self._counters_lock = threading.Lock()
        self._counters: dict[str, Counter] = {}

        self._meter: Meter
        self._logger: Logger
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None
        self._shutdown = False
        self._initialize_otel_resources(endpoint, api_key)

    @property
    def _root(self) -> OtelProvider:
        return self

    def _initialize_otel_resources(
        self,
        endpoint: str | None,
        api_key: str,
        export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    ) -> bool:
        """Initialize the OTel providers.

        This should only be called once during OtelProvider initialization.
        """
        if not self._enabled:
            return False

        endpoint = _otel_endpoint(endpoint)
        base_url = endpoint + "/sdk/otel/v1"

        try:
            resource = Resource.create({"service.name": _OTEL_SERVICE_NAME})

            _configure_session_auth(self._session, api_key)

            _redirect_otlp_http_exporter_logs()

            # Setup metrics exporter
            metric_exporter = OTLPMetricExporter(
                endpoint=f"{base_url}/metrics",
                session=self._session,
                timeout=_OTLP_HTTP_TIMEOUT_SECONDS,
            )
            reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=export_interval_ms,
            )
            self._meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[reader],
            )
            self._meter = self._meter_provider.get_meter("wandb")

            # Setup logs exporter
            log_exporter = OTLPLogExporter(
                endpoint=f"{base_url}/logs",
                session=self._session,
                timeout=_OTLP_HTTP_TIMEOUT_SECONDS,
            )
            self._logger_provider = LoggerProvider(resource=resource)
            self._logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter),
            )
            self._logger = self._logger_provider.get_logger("wandb.sdk")

            self._booted = True
        except Exception:
            _logger.exception("OtelProvider boot failed")
            self._enabled = False
            self._booted = False
            self._meter = NoOpMeter("wandb.sdk")
            self._logger = NoOpLogger("wandb.sdk")
            return False

        return True

    def shutdown(self, timeout_millis: float = 30_000) -> None:
        """Flush pending records and shut down the OpenTelemetry providers.

        After shutdown this provider and every recorder derived from it become
        no-ops. It should be called once when telemetry is no longer needed;
        additional calls are no-ops.
        """
        # Best-effort guard against repeated shutdowns. A concurrent double
        # call is harmless: the OpenTelemetry providers' own shutdown is
        # idempotent, and any error is suppressed below.
        if self._shutdown:
            return
        self._shutdown = True
        self._enabled = False

        if self._meter_provider is not None:
            with contextlib.suppress(Exception):
                self._meter_provider.shutdown(timeout_millis=timeout_millis)
        if self._logger_provider is not None:
            with contextlib.suppress(Exception):
                self._logger_provider.shutdown()


class NoOpOtelProvider(OtelProvider):
    """A no-op `OtelProvider` that does nothing."""

    def __init__(self) -> None:
        self._enabled = False
        self._pid = os.getpid()
        self._context = TelemetryContext()
        self._meter = NoOpMeter("wandb.sdk")
        self._logger = NoOpLogger("wandb.sdk")

    def shutdown(self, timeout_millis: float = 0) -> None:
        pass


class _ChildRecorder(TelemetryRecorder):
    """A derived recorder that shares its root provider's OpenTelemetry state.

    Created via `TelemetryRecorder.with_context`. A child carries its own
    derived telemetry context but does not own any OpenTelemetry providers, so
    it cannot be shut down; only the root `OtelProvider` can.
    """

    def __init__(self, root: OtelProvider, context: TelemetryContext) -> None:
        self._root_provider = root
        self._context = context

    @property
    def _root(self) -> OtelProvider:
        return self._root_provider


_singleton: OtelProvider | None = None
_singleton_lock = threading.Lock()


def setup_otel(
    *,
    api_key: str,
) -> OtelProvider:
    global _singleton
    pid = os.getpid()
    with _singleton_lock:
        if _singleton is not None and _singleton._pid == pid:
            return _singleton

        if not api_key:
            return NoOpOtelProvider()

        _singleton = OtelProvider(
            api_key=api_key,
            pid=pid,
        )
        return _singleton


def get_otel() -> OtelProvider:
    """Returns the global singleton `OtelProvider` instance.

    This should be called after `setup_otel` has been called.
    If `setup_otel` has not been called, this will return a no-op provider.
    """
    global _singleton
    pid = os.getpid()
    with _singleton_lock:
        if _singleton is None or _singleton._pid != pid:
            _logger.warning(
                "OtelProvider not setup in this process,"
                + " no telemetry will be recorded."
            )
            return NoOpOtelProvider()
        return _singleton


def _exception_stacktrace(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _otel_endpoint(endpoint: str | None) -> str:
    if endpoint is None:
        endpoint = (
            os.environ.get(env.TELEMETRY_ENDPOINT)
            or os.environ.get(env.BASE_URL)
            or _DEFAULT_ENDPOINT
        )
    return endpoint.rstrip("/")


class _WandbLoggerForwardingHandler(logging.Handler):
    def __init__(self, wandb_logger: logging.Logger) -> None:
        super().__init__()
        self._wandb_logger = wandb_logger

    def handle(self, record: logging.LogRecord) -> bool:
        with contextlib.suppress(Exception):
            self._wandb_logger.handle(record)
        return True


_redirect_lock = threading.Lock()
_redirected_pid: int | None = None


def _redirect_otlp_http_exporter_logs() -> None:
    """Redirect OTLP HTTP exporter logs to W&B's internal logger.

    The OTLP exporters log through module-level loggers obtained from the
    process-global `logging` registry.
    So intercepting their output needs to mutate global state.
    To keep that mutation contained, this runs at most once per process.
    """
    global _redirected_pid
    pid = os.getpid()

    with _redirect_lock:
        if _redirected_pid == pid:
            return
        _redirected_pid = pid

        wandb_logger = logging.getLogger("wandb")
        for logger_name in _OTLP_HTTP_EXPORTER_LOGGERS:
            exporter_logger = logging.getLogger(logger_name)
            exporter_logger.handlers = [
                handler
                for handler in exporter_logger.handlers
                if not isinstance(handler, _WandbLoggerForwardingHandler)
            ]
            exporter_logger.addHandler(_WandbLoggerForwardingHandler(wandb_logger))
            exporter_logger.propagate = False
            exporter_logger.setLevel(logging.NOTSET)


def _configure_session_auth(session: requests.Session, api_key: str | None) -> None:
    session.auth = requests_auth.HTTPBasicAuth("api", api_key) if api_key else None
