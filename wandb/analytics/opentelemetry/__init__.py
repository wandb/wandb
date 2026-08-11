"""OpenTelemetry-based analytics for the wandb SDK.

Forwards telemetry events (metrics and logs) to wandb-core.
Wandb-core then forwards the telemetry events to the W&B backend for ingestion
into Datadog.
"""

__all__ = (
    "TelemetryContext",
    "TelemetryRecorder",
    "clear_telemetry_recorder_pool",
    "get_telemetry_recorder",
)

from .opentelemetry_proxy import (
    TelemetryContext,
    TelemetryRecorder,
    clear_telemetry_recorder_pool,
    get_telemetry_recorder,
)
