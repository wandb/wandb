from __future__ import annotations

import atexit
import contextlib
import functools
import os
import platform
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Concatenate

import requests
from opentelemetry._logs import NoOpLoggerProvider, SeverityNumber
from opentelemetry.metrics import Counter, NoOpMeterProvider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import AggregationTemporality
from typing_extensions import Never, ParamSpec

from wandb import env
from wandb.sdk import wandb_setup
from wandb.sdk.wandb_settings import Settings

if TYPE_CHECKING:
    from opentelemetry.sdk.resources import Resource

# defaultExportInterval mirror: how often batched metrics/logs are flushed to
# the backend proxy.
_DEFAULT_EXPORT_INTERVAL_MILLIS = 60_000

# defaultExportTimeout mirror: total time allowed for a single export to
# collect and send its records.
_DEFAULT_EXPORT_TIMEOUT_MILLIS = 5_000

# httpClientTimeout mirror: per-request timeout for HTTP calls to the backend.
_HTTP_CLIENT_TIMEOUT_SECONDS = 10

# probeTimeout is the timeout for the server capability probe. The probe runs
# during SDK initialization, so it must be shorter than the initialization
# timeout rather than consuming the whole request budget.
_PROBE_TIMEOUT_SECONDS = 5

# Backend OpenTelemetry proxy ingestion paths, appended to the base URL.
_METRICS_PATH = "/sdk/otel/v1/metrics"
_LOGS_PATH = "/sdk/otel/v1/logs"

_DEFAULT_SERVICE_NAME = "sdk-wandb"

# _disabled gates OpenTelemetryProxy for the whole process. Once set, no new
# proxy is created and telemetry becomes a no-op.
_disabled = threading.Event()


def _check_server_supports_open_telemetry_proxy(settings: Settings) -> bool:
    """Return whether the server exposes the OpenTelemetry proxy endpoint."""
    try:
        response = requests.post(
            settings.base_url.rstrip("/") + _METRICS_PATH,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return False
    status_code = response.status_code
    response.close()

    # Depending on the server configuration, an unsupported endpoint may
    # respond with either 404 Not Found or 405 Method Not Allowed.
    return status_code not in (
        requests.codes.not_found,
        requests.codes.method_not_allowed,
    )


def disable() -> None:
    """Turn analytics off for the whole process.

    Once called, `get_open_telemetry_proxy` returns `None` and existing
    proxies' `increment_counter` and `log` methods become no-ops.
    """
    _disabled.set()


@dataclass(frozen=True)
class LowCardinalityAttributes:
    """Bounded set of low-cardinality attributes emitted as metric dimensions.

    Each declared field corresponds to a tag whose value MUST come from a
    small, bounded set. Restricting the attributes to this fixed set of fields
    keeps the number of metric dimensions bounded.

    Because the attributes are the declared fields, instances are valid by
    construction; unset fields are simply omitted when converted via `as_dict`.
    """

    python_runtime: str | None = None
    wandb_version: str | None = None
    python_version: str | None = None
    exception_type: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Return the set (non-`None`) attributes as a string-keyed mapping."""
        return {
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        }

    def merge(self, other: LowCardinalityAttributes) -> LowCardinalityAttributes:
        return LowCardinalityAttributes(
            python_runtime=self.python_runtime or other.python_runtime,
            wandb_version=self.wandb_version or other.wandb_version,
            python_version=self.python_version or other.python_version,
            exception_type=self.exception_type or other.exception_type,
        )


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

    def __init__(
        self,
        low_cardinality_attributes: LowCardinalityAttributes | None = None,
        high_cardinality_attributes: dict[str, str] | None = None,
    ) -> None:
        from wandb import __version__

        low_cardinality_attributes = (
            low_cardinality_attributes
            or LowCardinalityAttributes(
                python_runtime=platform.python_implementation(),
                wandb_version=__version__,
                python_version=platform.python_version(),
            )
        )

        # Fill in any attribute the caller did not provide with a value
        # computed from the current process. Provided values take precedence.
        self.low_cardinality_attributes = LowCardinalityAttributes(
            python_runtime=(
                low_cardinality_attributes.python_runtime
                or platform.python_implementation()
            ),
            wandb_version=(low_cardinality_attributes.wandb_version or __version__),
            python_version=(
                low_cardinality_attributes.python_version or platform.python_version()
            ),
        )
        self.high_cardinality_attributes: dict[str, str] = dict(
            high_cardinality_attributes or {}
        )

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

        Only the fields declared on `LowCardinalityAttributes` can be supplied,
        so the merged low-cardinality keys stay within the allowed set.
        """
        new_low_cardinality_attributes = LowCardinalityAttributes(
            python_runtime=(
                low_cardinality_attributes.python_runtime
                or self.low_cardinality_attributes.python_runtime
            ),
            wandb_version=(
                low_cardinality_attributes.wandb_version
                or self.low_cardinality_attributes.wandb_version
            ),
            python_version=(
                low_cardinality_attributes.python_version
                or self.low_cardinality_attributes.python_version
            ),
        )

        new_high_cardinality_attributes = {
            **self.high_cardinality_attributes,
            **high_cardinality_attributes,
        }

        return TelemetryContext(
            low_cardinality_attributes=new_low_cardinality_attributes,
            high_cardinality_attributes=new_high_cardinality_attributes,
        )


_P = ParamSpec("_P")


def guard(
    method: Callable[Concatenate[TelemetryRecorder, _P], None],
) -> Callable[Concatenate[TelemetryRecorder, _P], None]:
    """Wrap a telemetry method so only runs when wandb-core is initialized.

    Additionally it suppresses any exceptions raised by the wrapped method.
    To ensure telemetry is best-effort, and does not interfere with user code.
    """

    @functools.wraps(method)
    def wrapper(
        self: TelemetryRecorder,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> None:
        with contextlib.suppress(Exception):
            if not self._enabled or self._open_telemetry_proxy is None:
                return

            method(self, *args, **kwargs)

    return wrapper


class TelemetryRecorder:
    """Records OpenTelemetry events (metrics and logs).

    Recorders form a hierarchy: `with_context` derives a child recorder with
    additional attributes. Child recorders share their parent's service API,
    so telemetry is published through the same wandb-core API instance.

    All recording methods are no-ops unless a wandb-core service connection
    already exists.
    """

    _context: TelemetryContext

    def __init__(
        self,
        open_telemetry_proxy: OpenTelemetryProxy | None = None,
        context: TelemetryContext | None = None,
    ) -> None:
        """Initialize a TelemetryRecorder.

        Args:
            service_api: The service API used to publish telemetry.
                When omitted, telemetry calls are no-ops.
            context: The attributes to add to each emitted record.
        """
        self._enabled = bool(env.error_reporting_enabled())
        self._open_telemetry_proxy = open_telemetry_proxy
        self._context = context or TelemetryContext()

    def with_context(
        self,
        low_cardinality_attributes: LowCardinalityAttributes | None = None,
        high_cardinality_attributes: dict[str, str] | None = None,
    ) -> TelemetryRecorder:
        """Return a derived recorder with additional attributes.

        The derived recorder shares this recorder's service API but carries a
        child telemetry context that inherits this recorder's attributes merged
        with the supplied ones. This recorder is unchanged: attributes added to
        the derived recorder never appear on records emitted through this
        recorder or its siblings.
        """
        return TelemetryRecorder(
            self._open_telemetry_proxy,
            self._context.with_attributes(
                low_cardinality_attributes or LowCardinalityAttributes(),
                high_cardinality_attributes or {},
            ),
        )

    @guard
    def increment_counter(
        self,
        name: str,
        low_cardinality_attributes: LowCardinalityAttributes,
    ) -> None:
        """Increment an OpenTelemetry counter metric by 1.

        The counter metric contains the low-cardinality attributes
        from the current context plus the low-cardinality attributes
        passed when this method is called.
        """
        assert self._open_telemetry_proxy is not None

        merged_attributes = low_cardinality_attributes.merge(
            self._context.low_cardinality_attributes
        )
        self._open_telemetry_proxy.increment_counter(
            name,
            merged_attributes.as_dict(),
        )

    @guard
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
        assert self._open_telemetry_proxy is not None

        merged_attributes = {
            **self._context.low_cardinality_attributes.as_dict(),
            **self._context.high_cardinality_attributes,
            **(attributes or {}),
        }
        self._open_telemetry_proxy.log(
            message,
            merged_attributes,
            severity,
        )

    @guard
    def increment_counter_and_log_event(
        self,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter metric by 1 and log an event with the given name."""
        self.increment_counter(name, self._context.low_cardinality_attributes)
        self.log(name, attributes=attributes, severity=SeverityNumber.INFO)

    @guard
    def exception(
        self,
        exc: Exception,
        message: str | None = None,
    ) -> None:
        """Record an exception as both a counter metric and an error log.

        If a message is not provided,
        the exception's string representation is used.

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
        self.increment_counter(
            "exception",
            low_cardinality_attributes=LowCardinalityAttributes(
                exception_type=type(exc).__name__,
            ),
        )

        self.log(
            message or str(exc),
            severity=SeverityNumber.ERROR,
            attributes={
                "exception.type": type(exc).__name__,
                "exception.stacktrace": _exception_stacktrace(exc),
                "exception.message": str(exc),
            },
        )

    def reraise(self, exc: Exception) -> Never:
        """Log the exception to telemetry, then re-raise it."""
        # `exception` is guarded by `guard` decorator,
        # so recording telemetry here can never mask
        # or replace the exception we re-raise.
        self.exception(exc)
        raise exc


class OpenTelemetryProxy:
    """Exports OpenTelemetry metrics and logs to the W&B backend proxy API.

    The proxy owns the OpenTelemetry SDK meter and log providers along with
    their OTLP/HTTP exporters, and should be shut down when telemetry is no longer needed.

    This class should not be used directly.
    Instead, use the `TelemetryRecorder` class to record all telemetry.
    """

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        pid: int | None = None,
    ) -> OpenTelemetryProxy | None:
        """Create a proxy from settings, or None if telemetry is disabled."""
        if _disabled.is_set() or settings._offline:
            return None
        return cls(settings=settings, pid=pid)

    def __init__(
        self,
        *,
        settings: Settings,
        pid: int | None = None,
    ) -> None:
        """Initialize the proxy and its OpenTelemetry providers.

        Args:
            settings: The settings to use to configure the proxy.
        """
        self._pid = pid or os.getpid()

        # Providers are initialized after we verify the server supports proxying telemetry.
        self._meter_provider: MeterProvider | NoOpMeterProvider = NoOpMeterProvider()
        self._logger_provider: LoggerProvider | NoOpLoggerProvider = (
            NoOpLoggerProvider()
        )

        # Counters are cached by name so the same instrument is reused across
        # calls, avoiding duplicate-instrument warnings from the SDK.
        self._counters: dict[str, Counter] = {}
        self._counters_lock = threading.Lock()

        # Probe the server support for OpenTelemetry proxy.
        # shutdown guards Shutdown so the providers are only shut down once.
        self._shutdown = False
        self._shutdown_lock = threading.Lock()
        self._disabled = _disabled.is_set() or settings._offline
        self._probe_complete = threading.Event()
        if not self._disabled:
            self._start_server_probe(settings)
        else:
            self._probe_complete.set()

    def _start_server_probe(self, settings: Settings) -> None:
        """Probe server support without blocking proxy creation."""

        def probe_server_support() -> None:
            """Disable this proxy if the server does not support OpenTelemetry."""
            try:
                if not _check_server_supports_open_telemetry_proxy(settings):
                    self._disabled = True
                    return

                self._initialize_providers(settings)
            finally:
                self._probe_complete.set()

        if self._probe_complete.is_set():
            return

        self._probe_thread = threading.Thread(
            target=probe_server_support,
            daemon=True,
        )
        self._probe_thread.start()

    def _initialize_providers(self, settings: Settings) -> None:
        """Initialize the OpenTelemetry providers for exporting telemetry."""
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource

        session = requests.Session()
        resource = Resource.create({SERVICE_NAME: _DEFAULT_SERVICE_NAME})
        self._meter_provider = self._build_meter_provider(
            resource=resource,
            endpoint=settings.base_url,
            session=session,
        )
        self._logger_provider = self._build_logger_provider(
            resource=resource,
            endpoint=settings.base_url,
            session=session,
        )

    def _build_meter_provider(
        self,
        *,
        resource: Resource,
        endpoint: str,
        session: requests.Session,
    ) -> MeterProvider:
        """Build a meter provider that exports metrics via OTLP/HTTP."""
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import Counter as SdkCounter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        exporter = OTLPMetricExporter(
            endpoint=endpoint.rstrip("/") + _METRICS_PATH,
            session=session,
            timeout=_HTTP_CLIENT_TIMEOUT_SECONDS,
            preferred_temporality={SdkCounter: AggregationTemporality.DELTA},
        )
        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=_DEFAULT_EXPORT_INTERVAL_MILLIS,
            export_timeout_millis=_DEFAULT_EXPORT_TIMEOUT_MILLIS,
        )
        return MeterProvider(resource=resource, metric_readers=[reader])

    def _build_logger_provider(
        self,
        *,
        resource: Resource,
        endpoint: str,
        session: requests.Session,
    ) -> LoggerProvider:
        """Build a logger provider that exports logs via OTLP/HTTP."""
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        exporter = OTLPLogExporter(
            endpoint=endpoint.rstrip("/") + _LOGS_PATH,
            session=session,
            timeout=_HTTP_CLIENT_TIMEOUT_SECONDS,
        )
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                exporter,
                schedule_delay_millis=_DEFAULT_EXPORT_INTERVAL_MILLIS,
                export_timeout_millis=_DEFAULT_EXPORT_TIMEOUT_MILLIS,
            )
        )
        return provider

    def increment_counter(
        self,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Increment the counter metric `name` by 1 with the given attributes."""
        self._probe_complete.wait(timeout=_PROBE_TIMEOUT_SECONDS)
        if self._shutdown or self._disabled or _disabled.is_set():
            return

        counter = self._counter(name)
        counter.add(1, attributes or {})

    def _counter(self, name: str) -> Counter:
        with self._counters_lock:
            counter = self._counters.get(name)
            if counter is None:
                meter = self._meter_provider.get_meter(_DEFAULT_SERVICE_NAME)
                counter = meter.create_counter(name)
                self._counters[name] = counter
            return counter

    def log(
        self,
        body: str,
        attributes: dict[str, str] | None = None,
        severity: SeverityNumber = SeverityNumber.INFO,
    ) -> None:
        """Emit a log record with the given body, attributes, and severity."""
        self._probe_complete.wait(timeout=_PROBE_TIMEOUT_SECONDS)
        if self._shutdown or self._disabled or _disabled.is_set():
            return

        logger = self._logger_provider.get_logger(_DEFAULT_SERVICE_NAME)
        logger.emit(
            body=body,
            severity_number=severity,
            severity_text=severity.name,
            attributes=attributes or {},
        )

    def shutdown(self, timeout_millis: float = 30_000) -> None:
        """Flush pending records and shut down the providers.

        After this returns, the proxy becomes a no-op. Additional calls are
        ignored. Should be called once when telemetry is no longer needed.
        """
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True

        if isinstance(self._meter_provider, MeterProvider):
            with contextlib.suppress(Exception):
                self._meter_provider.shutdown(timeout_millis=timeout_millis)
        if isinstance(self._logger_provider, LoggerProvider):
            with contextlib.suppress(Exception):
                self._logger_provider.shutdown()


def _exception_stacktrace(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


_singleton_telemetry_proxy: OpenTelemetryProxy | None = None
_singleton_telemetry_recorder: TelemetryRecorder | None = None
_singleton_lock = threading.Lock()


def _shutdown_singleton_open_telemetry_proxy() -> None:
    """Flush and shut down the process-wide OpenTelemetry proxy on interpreter exit."""
    proxy = _singleton_telemetry_proxy
    if proxy is None:
        return
    with contextlib.suppress(Exception):
        proxy.shutdown()


def get_telemetry_recorder() -> TelemetryRecorder:
    """Return the process-wide TelemetryRecorder wrapping the singleton proxy.

    The same instance is reused until the proxy is replaced (for example after
    fork) or `disable()` is called. After disable, a no-op recorder is cached.
    """
    global _singleton_telemetry_recorder

    telemetry_proxy = get_open_telemetry_proxy()
    with _singleton_lock:
        recorder = _singleton_telemetry_recorder
        if recorder is None or recorder._open_telemetry_proxy is not telemetry_proxy:
            recorder = TelemetryRecorder(telemetry_proxy)
            _singleton_telemetry_recorder = recorder
        return recorder


def get_open_telemetry_proxy() -> OpenTelemetryProxy | None:
    """Return the singleton OpenTelemetryProxy instance."""
    global _singleton_telemetry_proxy

    if _disabled.is_set():
        return None

    pid = os.getpid()

    with _singleton_lock:
        if _singleton_telemetry_proxy is None or _singleton_telemetry_proxy._pid != pid:
            settings = wandb_setup.singleton().settings
            _singleton_telemetry_proxy = OpenTelemetryProxy.from_settings(
                settings=settings,
                pid=pid,
            )
            if _singleton_telemetry_proxy is not None:
                atexit.register(_shutdown_singleton_open_telemetry_proxy)

    return _singleton_telemetry_proxy
