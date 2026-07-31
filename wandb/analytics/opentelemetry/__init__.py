"""OpenTelemetry-based analytics for the wandb SDK.

Provides a protobuf-free OTLP/JSON telemetry proxy and its custom exporters.
"""

__all__ = (
    "TelemetryContext",
    "TelemetryRecorder",
)

from .opentelemetry_proxy import TelemetryContext, TelemetryRecorder
