from typing import Any

from wandb.sdk.automations import actions, automations, events, expr, scopes

from .actions import ActionType, Severity
from .api import create, define, delete, fetch
from .automations import NewAutomation
from .events import EventType, NewEventInput
from .scopes import ScopeType


def on(event_type: EventType, obj: Any) -> NewEventInput:
    match event_type:
        case events.LINK_ARTIFACT:
            return events.NewLinkArtifact(scope=obj)
        case events.ADD_ARTIFACT_ALIAS:
            raise NotImplementedError
        case events.CREATE_ARTIFACT:
            raise NotImplementedError
        case _:
            raise NotImplementedError(
                f"Unrecognized or unsupported event type ({event_type!r}) on {obj!r}"
            )
