from wandb._pydantic import IS_PYDANTIC_V2

from . import _filters as filters
from . import actions, automations, events, scopes
from .actions import ActionType, DoNothing, DoNotification, DoWebhook
from .automations import Automation, NewAutomation, PreparedAutomation
from .events import (
    ArtifactEvent,
    EventType,
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
        "The W&B Automations API is not supported in Pydantic v1 at this time. "
        "If at all possible, we currently recommend upgrading to Pydantic v2 to use this feature.",
    )

else:
    # If Pydantic v2 is available, we can use the full Automations API
    # but communicate to users that the API is still experimental and
    # may change rapidly.
    import warnings

    warnings.warn(
        "The W&B Automations API is currently experimental. Although we'll communicate "
        "breaking changes in release notes and attempt to minimize them in general, "
        "please know that such changes may occur between release versions without notice. "
        "We strongly recommend pinning your `wandb` version when using the Automations API "
        "to avoid unexpected breakages.",
        FutureWarning,
        stacklevel=1,
    )
# ----------------------------------------------------------------------------

__all__ = [
    "filters",
    "scopes",
    "events",
    "actions",
    "automations",
    # Scopes
    "ScopeType",
    "ArtifactCollectionScope",
    "ProjectScope",
    # Events
    "EventType",
    "OnAddArtifactAlias",
    "OnCreateArtifact",
    "OnLinkArtifact",
    "OnRunMetric",
    "ArtifactEvent",
    "RunEvent",
    # Actions
    "ActionType",
    "DoNotification",
    "DoWebhook",
    "DoNothing",
    # Automations
    "Automation",
    "NewAutomation",
    "PreparedAutomation",
    # Integrations
    "Integration",
    "SlackIntegration",
    "WebhookIntegration",
]
