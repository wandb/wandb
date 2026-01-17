import wandb

from .actions import ActionType, DoNothing, SendNotification, SendWebhook
from .automations import Automation, NewAutomation
from .events import (
    ArtifactEvent,
    EventType,
    MetricChangeFilter,
    MetricThresholdFilter,
    MetricZScoreFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    OnRunState,
    RunEvent,
    RunStateFilter,
)
from .integrations import Integration, SlackIntegration, WebhookIntegration
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

# ----------------------------------------------------------------------------
# WARNINGS on import
# The Automations API is still experimental and may change rapidly.
wandb.termwarn(
    "The W&B Automations API is experimental and the implementation is subject to change."
    "Review the release notes before upgrading. We recommend pinning your "
    f"package version to `{wandb.__package__}=={wandb.__version__}` to reduce the risk of disruption.",
    repeat=False,
)
# ----------------------------------------------------------------------------

__all__ = [
    # Scopes
    "ScopeType",  # doc:exclude
    "ArtifactCollectionScope",  # doc:exclude
    "ProjectScope",  # doc:exclude
    # Events
    "EventType",  # doc:exclude
    "OnAddArtifactAlias",
    "OnCreateArtifact",
    "OnLinkArtifact",
    "OnRunMetric",
    "OnRunState",
    "ArtifactEvent",  # doc:exclude
    "RunEvent",  # doc:exclude
    "MetricThresholdFilter",
    "MetricChangeFilter",
    "RunStateFilter",
    "MetricZScoreFilter",
    # Actions
    "ActionType",  # doc:exclude
    "SendNotification",
    "SendWebhook",
    "DoNothing",
    # Automations
    "Automation",
    "NewAutomation",
    # Integrations
    "Integration",  # doc:exclude
    "SlackIntegration",  # doc:exclude
    "WebhookIntegration",  # doc:exclude
]
