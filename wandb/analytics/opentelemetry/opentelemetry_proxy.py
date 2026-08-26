from __future__ import annotations

import contextlib
import functools
import platform
import traceback
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Concatenate

from opentelemetry._logs import SeverityNumber
from typing_extensions import Never, ParamSpec

from wandb import env
from wandb.proto.wandb_api_pb2 import ApiRequest
from wandb.proto.wandb_otel_pb2 import (
    LowCardinalityAttributes as LowCardinalityAttributesProto,
)
from wandb.proto.wandb_otel_pb2 import (
    OpenTelemetryCounterRequest,
    OpenTelemetryLogRequest,
    OpenTelemetryRequest,
)

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi


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
            if self._service_api is None or not self._service_api.initialized:
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
        service_api: ServiceApi | None = None,
        context: TelemetryContext | None = None,
    ) -> None:
        """Initialize a TelemetryRecorder.

        Args:
            service_api: The service API used to publish telemetry.
                When omitted, telemetry calls are no-ops.
            context: The attributes to add to each emitted record.
        """
        self._service_api = service_api if env.error_reporting_enabled() else None
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
            self._service_api,
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
        assert self._service_api is not None

        merged_attributes = low_cardinality_attributes.merge(
            self._context.low_cardinality_attributes
        )
        otel_metric_request = OpenTelemetryCounterRequest(
            name=name,
            low_cardinality_attributes=LowCardinalityAttributesProto(
                python_runtime=merged_attributes.python_runtime,
                wandb_version=merged_attributes.wandb_version,
                python_version=merged_attributes.python_version,
                exception_type=merged_attributes.exception_type,
            ),
        )

        self._service_api.api_publish(
            ApiRequest(
                open_telemetry_request=OpenTelemetryRequest(
                    open_telemetry_counter_request=otel_metric_request,
                ),
            ),
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
        assert self._service_api is not None

        merged_attributes = {
            **self._context.low_cardinality_attributes.as_dict(),
            **self._context.high_cardinality_attributes,
            **(attributes or {}),
        }
        otel_log_request = OpenTelemetryLogRequest(
            message=message,
            attributes=merged_attributes,
            severity=severity.value,
        )

        self._service_api.api_publish(
            ApiRequest(
                open_telemetry_request=OpenTelemetryRequest(
                    open_telemetry_log_request=otel_log_request,
                ),
            ),
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


def _exception_stacktrace(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
