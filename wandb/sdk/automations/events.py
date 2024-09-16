from __future__ import annotations

from enum import StrEnum, global_enum
from typing import ClassVar, Literal, NoReturn, TypeAlias, Union

from pydantic import ConfigDict, Field, Json
from typing_extensions import Annotated

from wandb.sdk.automations._typing import TypenameField
from wandb.sdk.automations.actions import NewActionInput
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.expr.op import AnyExpr, FieldFilter, all_of, any_of
from wandb.sdk.automations.generated.schema_gen import ArtifactCollection, Project


# Legacy names
@global_enum
class EventType(StrEnum):
    ADD_ARTIFACT_ALIAS = "ADD_ARTIFACT_ALIAS"
    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    LINK_ARTIFACT = "LINK_MODEL"
    UPDATE_ARTIFACT_ALIAS = "UPDATE_ARTIFACT_ALIAS"


ADD_ARTIFACT_ALIAS = EventType.ADD_ARTIFACT_ALIAS
CREATE_ARTIFACT = EventType.CREATE_ARTIFACT
LINK_ARTIFACT = EventType.LINK_ARTIFACT
UPDATE_ARTIFACT_ALIAS = EventType.UPDATE_ARTIFACT_ALIAS


class EventFilter(Base):
    filter: Json[AnyExpr]


class Event(Base):
    typename__: TypenameField[Literal["FilterEventTriggeringCondition"]]
    event_type: EventType
    filter: Json[EventFilter]


# TODO: This is a WIP Triggers on run metrics
class RunMetricEvent(Base):
    typename__: TypenameField[Literal["RunMetricTriggeringCondition"]]
    event_type: str  # TODO: TBD

    run_filter: Json[EventFilter]
    metric_filter: Json[FieldFilter]


class NewEventInput(Base):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    scope: ArtifactCollection | Project
    event_type: EventType
    filter: Json[EventFilter]

    # TODO: Deprecate this
    def link_action(self, action: NewActionInput) -> NewEventAndAction:
        if isinstance(action, NewActionInput):
            return self, action
        raise TypeError(
            f"Expected an instance of {NewActionInput.__name__!r}, got: {type(action).__qualname__!r}"
        )

    def __rshift__(self, other: NewActionInput) -> NewEventAndAction:
        """Connect this event to an action using, e.g. `event >> action`."""
        return self.link_action(other)

    def __gt__(self, other: NewActionInput) -> NoReturn:
        """Let's not get too ahead of ourselves here, no overloading the comparison operators."""
        raise RuntimeError("Did you mean to use the '>>' operator?")


NewEventAndAction: TypeAlias = tuple[NewEventInput, NewActionInput]


class NewLinkArtifact(NewEventInput):
    _LINK_ARTIFACT_EVENT_FILTER: ClassVar[EventFilter] = EventFilter(
        filter=any_of(all_of()).model_dump_json()
    ).model_dump_json()

    scope: ArtifactCollection

    event_type: Literal[EventType.LINK_ARTIFACT] = LINK_ARTIFACT
    filter: Json[EventFilter] = _LINK_ARTIFACT_EVENT_FILTER


# ------------------------------------------------------------------------------


AnyEvent = Annotated[
    Union[
        Event,
        # RunMetricEvent,
    ],
    Field(alias="triggeringCondition"),
]
