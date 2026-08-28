"""OpenTelemetry-based analytics for the wandb SDK.

Forwards telemetry events (metrics and logs) to wandb-core.
Wandb-core then forwards the telemetry events to the W&B backend for ingestion
into Datadog.
"""

__all__ = (
    "TelemetryContext",
    "TelemetryRecorder",
    "OpenTelemetryProxy",
)

from .opentelemetry_proxy import OpenTelemetryProxy, TelemetryContext, TelemetryRecorder
