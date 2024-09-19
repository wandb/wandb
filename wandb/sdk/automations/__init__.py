from typing import Any

from wandb.sdk.automations import actions, automations, events, operators, scopes

from .actions import ActionType, Severity
from .api import create, define, delete, get_all, make_table
from .automations import NewAutomation
from .events import EventTrigger, EventType
from .scopes import ScopeType


def on(event: EventType, scope: Any, **kwargs) -> EventTrigger:
    match event:
        case events.LINK_ARTIFACT:
            return events.LinkArtifact(scope=scope)
        case events.ADD_ARTIFACT_ALIAS:
            return events.AddArtifactAlias.from_pattern(scope=scope, **kwargs)
        case events.CREATE_ARTIFACT:
            return events.CreateArtifact(scope=scope, **kwargs)
        case _:
            raise NotImplementedError(
                f"Unsupported event type ({event!r}) on {scope!r}"
            )
