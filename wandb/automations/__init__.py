import wandb
from wandb._pydantic import IS_PYDANTIC_V2

from .actions import ActionType, DoNothing, SendNotification, SendWebhook
from .automations import Automation, NewAutomation
from .events import (
    ArtifactEvent,
    EventType,
    MetricChangeFilter,
    MetricThresholdFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)
from .integrations import Integration, SlackIntegration, WebhookIntegration
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

# ----------------------------------------------------------------------------
# WARNINGS on import
if not IS_PYDANTIC_V2:
    # Raises an error in Pydantic v1 environments, where the Automations API
    # has not been tested and is unlikely to work as expected.
    #
    # Remove this when we either:
    # - Drop support for Pydantic v1
    # - Are able to implement (limited) Pydantic v1 support
    raise ImportError(
        "The W&B Automations API requires Pydantic v2. "
        "We recommend upgrading `pydantic` to use this feature."
    )

else:
    # If Pydantic v2 is available, we can use the full Automations API
    # but communicate to users that the API is still experimental and
    # may change rapidly.
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
    "ArtifactEvent",  # doc:exclude
    "RunEvent",  # doc:exclude
    "MetricThresholdFilter",
    "MetricChangeFilter",
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
