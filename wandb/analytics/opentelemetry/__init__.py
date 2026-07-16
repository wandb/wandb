"""OpenTelemetry-based analytics for the wandb SDK.

Provides a protobuf-free OTLP/JSON telemetry proxy and its custom exporters.
"""

__all__ = (
    "NoOpOtelProvider",
    "OtelProvider",
    "TelemetryRecorder",
    "get_otel",
    "setup_otel",
)

from .opentelemetry_proxy import (
    NoOpOtelProvider,
    OtelProvider,
    TelemetryRecorder,
    get_otel,
    setup_otel,
)
