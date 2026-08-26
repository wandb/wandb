"""OpenTelemetry-based analytics for the wandb SDK.

Forwards telemetry events (metrics and logs) to wandb-core.
Wandb-core then forwards the telemetry events to the W&B backend for ingestion
into Datadog.
"""

__all__ = (
    "TelemetryContext",
    "TelemetryRecorder",
)

from .opentelemetry_proxy import TelemetryContext, TelemetryRecorder
