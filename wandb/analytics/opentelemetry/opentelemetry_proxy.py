from __future__ import annotations

import atexit
import contextlib
import functools
import logging
import os
import platform
import threading
import traceback
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Concatenate, ParamSpec, TypeVar

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
from typing_extensions import Never

from wandb import env
from wandb.sdk.lib.wbauth import Auth

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

    def as_dict(self) -> dict[str, str]:
        """Return the set (non-`None`) attributes as a string-keyed mapping."""
        return {
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        }


def _guard(
    func: Callable[Concatenate[TelemetryRecorder, _P], _R | None],
) -> Callable[Concatenate[TelemetryRecorder, _P], _R | None]:
    """Gates `TelemetryRecorder` methods so they only run when it is safe to.

    A recorder is safe to use when:
    - The recorder has a OTelProvider.
    - Telemetry is enabled.
    - The recorder's OtelProvider belongs to the current process.
    """

    @functools.wraps(func)
    def wrapper(
        self: TelemetryRecorder,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R | None:
        root = self._root
        if not root:
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


class TelemetryRecorder:
    """Records OpenTelemetry events (metrics and logs).

    Recorders form a hierarchy: `with_context` derives a child recorder with
    additional attributes. Child recorders share the root provider's
    OpenTelemetry providers, and therefore do not need to be shut down.
    """

    _context: TelemetryContext

    def __init__(
        self,
        root: OtelProvider | None = None,
        context: TelemetryContext | None = None,
    ) -> None:
        """Initialize a TelemetryRecorder.

        Args:
            root: The root OtelProvider to use.
                If not provided, all telemetry calls will be no-ops.

                The root OtelProvider contains the resources for sending telemetry
                to the W&B backend. Telemetry recorders are not responsible for
                handling the shutdown of the root OtelProvider.
            context: The TelemetryContext to use.
        """
        self._root = root
        self._context = context or TelemetryContext()

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
        return TelemetryRecorder(
            self._root,
            self._context.with_attributes(
                low_cardinality_attributes or LowCardinalityAttributes(),
                high_cardinality_attributes or {},
            ),
        )

    @_guard
    def increment_counter_and_log_event(
        self,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter metric by 1 and log an event with the given name."""
        if not self._root:
            return

        self._root.increment_counter(
            name,
            self._context.low_cardinality_attributes,
        )
        self.log(
            message=name,
            attributes=attributes,
        )

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
        if not self._root:
            return

        merged_attributes = {
            **self._context.low_cardinality_attributes.as_dict(),
            **self._context.high_cardinality_attributes,
            **(attributes or {}),
        }
        self._root.log(message, merged_attributes, severity)

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
        if not self._root:
            return

        self._root.increment_counter(
            name="exception",
            low_cardinality_attributes=self._context.low_cardinality_attributes,
        )

        exception_attributes = {
            "exception.type": type(exc).__name__,
            "exception.stacktrace": _exception_stacktrace(exc),
            **self._context.low_cardinality_attributes.as_dict(),
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


class OtelProvider:
    """The root `TelemetryRecorder`, which owns the OpenTelemetry providers.

    The root is responsible for initializing and shutting down the underlying
    providers. Child recorders derived via `with_context` share these providers
    but do not own them.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        auth_provider: Callable[[], Auth | None] | None = None,
        pid: int | None = None,
    ) -> None:
        self._enabled = bool(env.error_reporting_enabled())
        self._pid = pid or os.getpid()
        self._session: requests.Session = requests.Session()

        # Counters should be created only once per name,
        # so we cache the counter object upon creation.
        self._counters_lock = threading.Lock()
        self._counters: dict[str, Counter] = {}

        self._meter: Meter = NoOpMeter("wandb.sdk")
        self._logger: Logger = NoOpLogger("wandb.sdk")
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None
        self._booted = False
        self._shutdown = False
        self._initialize_otel_resources(endpoint, auth_provider)

    def _initialize_otel_resources(
        self,
        endpoint: str | None,
        auth_provider: Callable[[], Auth | None] | None,
        export_interval_ms: int = _DEFAULT_EXPORT_INTERVAL_MS,
    ) -> bool:
        """Initialize the OTel providers.

        This should only be called once during OtelProvider initialization.
        """
        if not self._enabled or auth_provider is None:
            return False

        try:
            auth = auth_provider()
        except Exception:
            return False
        if auth is None:
            return False

        endpoint = _otel_endpoint(endpoint)
        base_url = endpoint + "/sdk/otel/v1"

        try:
            resource = Resource.create({"service.name": _OTEL_SERVICE_NAME})

            _configure_session_auth(self._session, auth)

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

    def increment_counter(
        self,
        name: str,
        low_cardinality_attributes: LowCardinalityAttributes,
    ) -> None:
        """Increment a counter metric with the given name by 1.

        The provided low-cardinality attributes are included as attributes
        on the metric record.
        """
        counter = self._counters.get(name)
        if counter is None:
            with self._counters_lock:
                counter = self._counters.get(name)
                if counter is None:
                    counter = self._meter.create_counter(name, unit="Count")
                    self._counters[name] = counter

        counter.add(1, attributes=low_cardinality_attributes.as_dict())

    def log(
        self,
        message: str,
        attributes: dict[str, str],
        severity: SeverityNumber = SeverityNumber.INFO,
    ) -> None:
        """Emit an OpenTelemetry log record with the specified severity level.

        The provided attributes are included on the log record.
        """
        self._logger.emit(
            body=message,
            severity_number=severity,
            attributes=attributes,
        )

    def shutdown(self, timeout_millis: float = 2_000) -> None:
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


_provider_cache_lock = threading.Lock()
_provider_cache: dict[str, OtelProvider] = {}
_provider_initialization_locks: defaultdict[str, threading.Lock] = defaultdict(
    threading.Lock
)


def _shutdown_otel_providers() -> None:
    with _provider_cache_lock:
        providers = list(_provider_cache.values())

    for provider in providers:
        provider.shutdown()


atexit.register(_shutdown_otel_providers)


def _setup_otel(
    *,
    base_url: str | None = None,
    auth_provider: Callable[[], Auth | None] | None = None,
) -> OtelProvider | None:
    pid = os.getpid()

    base_url = _otel_endpoint(base_url)
    with _provider_cache_lock:
        initialization_lock = _provider_initialization_locks[base_url]

    # Only hold the initialization lock while setting up a provider,
    # This allows multiple setups to occur for different endpoints at the same time.
    with initialization_lock:
        with _provider_cache_lock:
            otel_provider = _provider_cache.get(base_url)
            if otel_provider is not None and otel_provider._pid == pid:
                return otel_provider

        # If no OtelProvider has been found, and no auth provider is provided,
        # return None, since we can't setup a provider without auth.
        if auth_provider is None:
            return None

        otel_provider = OtelProvider(
            endpoint=base_url,
            auth_provider=auth_provider,
            pid=pid,
        )
        with _provider_cache_lock:
            _provider_cache[base_url] = otel_provider
        return otel_provider


def get_otel(
    base_url: str | None = None,
    *,
    auth_provider: Callable[[], Auth | None] | None = None,
) -> OtelProvider | None:
    """Return the `OtelProvider` cached for a server endpoint.

    If no provider has been set up and an auth provider is provided,
    a new one OtelProvider will be created.
    """
    pid = os.getpid()
    base_url = _otel_endpoint(base_url)

    with _provider_cache_lock:
        otel_provider = _provider_cache.get(base_url)

    if otel_provider is None or otel_provider._pid != pid:
        otel_provider = _setup_otel(
            base_url=base_url,
            auth_provider=auth_provider,
        )
    return otel_provider


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


def _configure_session_auth(
    session: requests.Session,
    auth: Auth,
) -> None:
    session.auth = auth.as_requests_auth()
