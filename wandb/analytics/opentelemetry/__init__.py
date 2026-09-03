"""OpenTelemetry-based analytics for the wandb SDK.

Forwards telemetry events (metrics and logs) to wandb-core.
Wandb-core then forwards the telemetry events to the W&B backend for ingestion
into Datadog.
"""

__all__ = (
    "OpenTelemetryProxy",
    "TelemetryContext",
    "TelemetryRecorder",
    "get_telemetry_recorder",
)

from .opentelemetry_proxy import (
    OpenTelemetryProxy,
    TelemetryContext,
    TelemetryRecorder,
    get_telemetry_recorder,
)
