from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import actions, automations, events, scopes
from ._ops.funcs import (
    and_,
    eq,
    gt,
    gte,
    lt,
    lte,
    ne,
    none_of,
    not_,
    on_field,
    or_,
    regex,
)
from .api import create, define, delete, get_all, get_one
from .automations import NewAutomation
from .events import NewEvent
from .misc import make_table
from .scopes import ArtifactCollection, Project

if TYPE_CHECKING:
    from ._generated.enums import EventTriggeringConditionType


def on(event: EventTriggeringConditionType, scope: Any, **kwargs: Any) -> NewEvent:
    from wandb.sdk.automations._generated.enums import EventTriggeringConditionType

    match event:
        case EventTriggeringConditionType.LINK_MODEL:
            return events.NewLinkArtifact(scope=scope)
        case EventTriggeringConditionType.ADD_ARTIFACT_ALIAS:
            return events.NewAddArtifactAlias.from_pattern(scope=scope, **kwargs)
        case EventTriggeringConditionType.CREATE_ARTIFACT:
            return events.NewCreateArtifact(scope=scope, **kwargs)
        case EventTriggeringConditionType.RUN_METRIC:
            return events.NewRunMetric(scope=scope, **kwargs)
        case _:
            raise NotImplementedError(
                f"Unsupported event type ({event!r}) on {scope!r}"
            )
